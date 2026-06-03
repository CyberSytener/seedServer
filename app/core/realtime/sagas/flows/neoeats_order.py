from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.neoeats_blocks import AccountingBlock, BillingBlock, InventoryBlock
from app.core.realtime.engine import BaseSaga, SagaStepDefinition, SagaStepResult
from app.models.neoeats import OrderStatusUpdate


class NeoEatsOrderFlow(BaseSaga):
    saga_type = "neoeats_order"

    async def run(
        self,
        saga_id: str,
        payload: Dict[str, Any],
        steps: List[Dict[str, Any]],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        order_id = payload.get("order_id") or str(uuid.uuid4())
        user_id = payload.get("user_id")
        items = payload.get("items") or []
        delivery = payload.get("delivery") or {}
        payment = payload.get("payment") or {}
        pricing = payload.get("pricing") or {}

        state: Dict[str, Any] = {
            "order_id": order_id,
            "user_id": user_id,
            "delivery": delivery,
            "items": items,
        }

        async def emit_status(status: str, message: Optional[str] = None) -> None:
            if not user_id:
                return
            stream = getattr(self, "order_stream", None)
            if not stream:
                return
            update = OrderStatusUpdate(
                order_id=order_id,
                saga_id=saga_id,
                status=status,
                message=message,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            await stream.publish(user_id, update.model_dump())

        async def resolve_items(raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            if not self.db:
                raise ValueError("Order saga requires saga db")

            resolved: List[Dict[str, Any]] = []
            for item in raw_items:
                item_id = item.get("item_id")
                sku = item.get("sku")
                name = item.get("name")
                quantity = float(item.get("quantity") or 0)
                price = item.get("price")
                if quantity <= 0:
                    raise ValueError("Order items must have positive quantity")

                if item_id == "custom_ai_dish":
                    if not name or price is None:
                        raise ValueError("custom_ai_dish requires name and price")
                    resolved.append(
                        {
                            "item_id": "custom_ai_dish",
                            "quantity": quantity,
                            "lot_id": None,
                            "price": float(price),
                            "name": name,
                            "sku": sku,
                            "is_custom": True,
                        }
                    )
                    continue

                if not item_id and sku:
                    row = await self.db.fetchrow(
                        "SELECT item_id FROM inventory_item WHERE sku = $1",
                        sku,
                    )
                    if row:
                        item_id = row["item_id"]

                if not item_id and name:
                    row = await self.db.fetchrow(
                        "SELECT item_id FROM inventory_item WHERE lower(name) = lower($1)",
                        name,
                    )
                    if row:
                        item_id = row["item_id"]

                if not item_id:
                    if not name or price is None:
                        raise ValueError("Custom order item requires name and price")
                    resolved.append(
                        {
                            "item_id": "custom_ai_dish",
                            "quantity": quantity,
                            "lot_id": None,
                            "price": float(price),
                            "name": name,
                            "sku": sku,
                            "is_custom": True,
                        }
                    )
                    continue

                resolved.append(
                    {
                        "item_id": item_id,
                        "quantity": quantity,
                        "lot_id": item.get("lot_id"),
                        "price": float(price) if price is not None else None,
                        "name": name,
                        "sku": sku,
                        "is_custom": False,
                    }
                )

            return resolved

        async def reserve_inventory() -> SagaStepResult:
            resolved_items = await resolve_items(items)
            reservable_items = [item for item in resolved_items if not item.get("is_custom")]
            state["order_items"] = resolved_items

            result: Dict[str, Any]
            if reservable_items:
                block = InventoryBlock(engine=self)
                result = await block.execute(
                    {},
                    {
                        "action": "reserve",
                        "order_id": order_id,
                        "items": [
                            {
                                "item_id": item["item_id"],
                                "quantity": item["quantity"],
                                "lot_id": item.get("lot_id"),
                            }
                            for item in reservable_items
                        ],
                    },
                )
                state["reservation_id"] = result.get("reservation_id")
            else:
                result = {
                    "ok": True,
                    "reservation_id": None,
                    "items": [],
                    "custom_only": True,
                }
                state["reservation_id"] = None

            await emit_status("PAYMENT_PENDING", "Payment processing started")
            return SagaStepResult(meta=result, result={"reservation_id": result.get("reservation_id")})

        async def release_inventory(action: Any) -> None:
            reservation_id = action.meta.get("reservation_id") if action.meta else None
            if not reservation_id:
                return
            block = InventoryBlock(engine=self)
            await block.execute({}, {"action": "release", "reservation_id": reservation_id})

        async def process_payment() -> SagaStepResult:
            payment_id = str(uuid.uuid4())
            await emit_status("LAB_PREP", "Kitchen started prepping your order")
            return SagaStepResult(result={"payment_status": "paid", "payment_id": payment_id})

        async def bill_order() -> SagaStepResult:
            block = BillingBlock(engine=self)
            cogs_total = 0.0
            for item in state.get("order_items") or []:
                price = float(item.get("price") or 0.0)
                cogs_total += price * float(item.get("quantity") or 0)

            result = await block.execute(
                {},
                {
                    "order_id": order_id,
                    "cogs_total": cogs_total,
                    "waste_overhead": float(pricing.get("waste_overhead") or 0.0),
                    "margin_pct": float(pricing.get("margin_pct") or 0.25),
                    "vat_pct": float(pricing.get("vat_pct") or 0.15),
                    "currency": pricing.get("currency") or payment.get("currency") or "NOK",
                },
            )
            state["billing"] = result
            return SagaStepResult(meta=result, result=result)

        async def post_accounting() -> SagaStepResult:
            block = AccountingBlock(engine=self)
            billing = state.get("billing") or {}
            result = await block.execute(
                {},
                {
                    "order_id": order_id,
                    "receipt_id": billing.get("receipt_id"),
                    "total": billing.get("total"),
                    "vat": billing.get("vat"),
                    "subtotal": billing.get("subtotal"),
                    "currency": billing.get("currency"),
                    "source": "order",
                },
            )
            await emit_status("COURIER_ASSIGNED", "Courier assigned and en route")
            return SagaStepResult(meta=result, result={"accounting": result})

        async def commit_inventory() -> SagaStepResult:
            reservation_id = state.get("reservation_id")
            if not reservation_id:
                await emit_status("DELIVERED", "Order delivered. Enjoy!")
                return SagaStepResult(meta={"ok": True, "custom_only": True}, result={"inventory_commit": True})
            block = InventoryBlock(engine=self)
            result = await block.execute(
                {},
                {"action": "commit", "reservation_id": reservation_id},
            )
            await emit_status("DELIVERED", "Order delivered. Enjoy!")
            return SagaStepResult(meta=result, result={"inventory_commit": True})

        step_plan = [
            SagaStepDefinition(
                name="reserve_inventory",
                execute=reserve_inventory,
                compensate=release_inventory,
                adapter_type="inventory",
            ),
            SagaStepDefinition(
                name="process_payment",
                execute=process_payment,
                adapter_type="payment",
            ),
            SagaStepDefinition(
                name="billing",
                execute=bill_order,
                adapter_type="billing",
            ),
            SagaStepDefinition(
                name="accounting",
                execute=post_accounting,
                adapter_type="accounting",
            ),
            SagaStepDefinition(
                name="commit_inventory",
                execute=commit_inventory,
                adapter_type="inventory",
            ),
        ]

        result = await self.execute_step_plan(
            saga_id=saga_id,
            saga_type=self.saga_type,
            payload=payload,
            steps=steps,
            step_plan=step_plan,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
        if isinstance(result, dict):
            result.setdefault("order_id", order_id)
        return result
