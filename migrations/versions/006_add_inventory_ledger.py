"""
Alembic migration: Create inventory ledger and financial tables

Generated: 2026-02-12
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "inventory_ledger_001"
down_revision = "stock_levels_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_item (
            item_id uuid PRIMARY KEY,
            sku text UNIQUE NOT NULL,
            name text NOT NULL,
            category text,
            unit text,
            is_active boolean NOT NULL DEFAULT true,
            created_at timestamptz DEFAULT now(),
            updated_at timestamptz DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_lot (
            lot_id uuid PRIMARY KEY,
            item_id uuid NOT NULL REFERENCES inventory_item(item_id),
            expires_at date,
            quantity_total numeric NOT NULL DEFAULT 0,
            quantity_available numeric NOT NULL DEFAULT 0,
            location_id uuid,
            created_at timestamptz DEFAULT now(),
            updated_at timestamptz DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_reservation (
            reservation_id uuid PRIMARY KEY,
            order_id uuid NOT NULL,
            status text NOT NULL,
            expires_at timestamptz,
            created_at timestamptz DEFAULT now(),
            updated_at timestamptz DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_reservation_line (
            reservation_id uuid NOT NULL REFERENCES inventory_reservation(reservation_id),
            lot_id uuid NOT NULL REFERENCES inventory_lot(lot_id),
            quantity numeric NOT NULL,
            PRIMARY KEY (reservation_id, lot_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_ledger_event (
            event_id uuid PRIMARY KEY,
            event_type text NOT NULL,
            item_id uuid NOT NULL REFERENCES inventory_item(item_id),
            lot_id uuid REFERENCES inventory_lot(lot_id),
            quantity numeric NOT NULL,
            source text,
            reference_id uuid,
            created_at timestamptz DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS financial_receipt (
            receipt_id uuid PRIMARY KEY,
            order_id uuid NOT NULL,
            subtotal numeric NOT NULL DEFAULT 0,
            vat numeric NOT NULL DEFAULT 0,
            total numeric NOT NULL DEFAULT 0,
            currency text NOT NULL DEFAULT 'NOK',
            created_at timestamptz DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS financial_journal (
            entry_id uuid PRIMARY KEY,
            order_id uuid NOT NULL,
            receipt_id uuid NOT NULL REFERENCES financial_receipt(receipt_id),
            amount numeric NOT NULL,
            vat numeric NOT NULL DEFAULT 0,
            currency text NOT NULL DEFAULT 'NOK',
            source text,
            created_at timestamptz DEFAULT now()
        )
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_inventory_lot_item_id ON inventory_lot(item_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_inventory_lot_expires_at ON inventory_lot(expires_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_inventory_reservation_order_id ON inventory_reservation(order_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_inventory_ledger_event_item_id ON inventory_ledger_event(item_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_financial_receipt_order_id ON financial_receipt(order_id)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_financial_receipt_order_id")
    op.execute("DROP INDEX IF EXISTS ix_inventory_ledger_event_item_id")
    op.execute("DROP INDEX IF EXISTS ix_inventory_reservation_order_id")
    op.execute("DROP INDEX IF EXISTS ix_inventory_lot_expires_at")
    op.execute("DROP INDEX IF EXISTS ix_inventory_lot_item_id")

    op.execute("DROP TABLE IF EXISTS financial_journal")
    op.execute("DROP TABLE IF EXISTS financial_receipt")
    op.execute("DROP TABLE IF EXISTS inventory_ledger_event")
    op.execute("DROP TABLE IF EXISTS inventory_reservation_line")
    op.execute("DROP TABLE IF EXISTS inventory_reservation")
    op.execute("DROP TABLE IF EXISTS inventory_lot")
    op.execute("DROP TABLE IF EXISTS inventory_item")
