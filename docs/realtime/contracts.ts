/**
 * Real-time Conversational AI - TypeScript Message Contracts
 * 
 * For use in web/frontend clients.
 * Auto-generated from Python Pydantic models.
 */

// ============================================================================
// ENUMS
// ============================================================================

export enum ActionStatus {
  PENDING = "pending",
  IN_PROGRESS = "in_progress",
  SUCCESS = "success",
  FAILED = "failed",
  REQUIRES_MANUAL_REVIEW = "requires_manual_review",
}

export enum SystemEventLevel {
  ERROR = "error",
  WARNING = "warning",
  INFO = "info",
}

// ============================================================================
// ACTION TYPES
// ============================================================================

export interface ActionMetadata {
  session_id: string;
  user_id?: string | null;
  timestamp: string; // ISO 8601
  confidence: number; // 0.0-1.0
  requires_user_confirmation: boolean;
  audit_tags?: string[];
}

export interface Action {
  name: string;
  id: string;
  params: Record<string, any>;
  metadata: ActionMetadata;
}

// ============================================================================
// CLIENT → SERVER MESSAGES
// ============================================================================

export interface ClientMessage {
  type: "client.message";
  text?: string | null;
  audio_ref?: string | null;
  file_ref?: string | null;
  metadata?: Record<string, any>;
}

export interface ClientCommand {
  type: "client.command";
  command: "stop" | "regenerate" | "upload_resume" | "clear_context";
  action_id?: string | null;
  payload?: Record<string, any>;
}

export interface ClientActionConfirm {
  type: "client.action.confirm";
  action_id: string;
  confirm: boolean;
  reason?: string | null;
}

export interface ActionInvoke {
  type: "action.invoke";
  action: Action;
  [key: string]: any; // allow additional payload fields (cv, criteria, etc.)
}

export interface ActionConfirm {
  type: "action.confirm";
  action_id: string;
  confirm: boolean;
  reason?: string | null;
}

export interface ActionCancel {
  type: "action.cancel";
  action_id: string;
  reason?: string | null;
}

export interface SagaStatusRequest {
  type: "saga.status";
  saga_id: string;
}

export type ClientMessageUnion =
  | ClientMessage
  | ClientCommand
  | ClientActionConfirm
  | ActionInvoke
  | ActionConfirm
  | ActionCancel
  | SagaStatusRequest;

// ============================================================================
// SERVER → CLIENT MESSAGES
// ============================================================================

export interface ModelPartial {
  type: "model.partial";
  chunk: string;
  delta?: string | null;
}

export interface ModelFinal {
  type: "model.final";
  content: string;
  metadata?: Record<string, any>;
}

export interface ModelInvokeAction {
  type: "model.invoke_action";
  action: Action;
}

export interface ActionResult {
  type: "action.result";
  action_id: string;
  action_name: string;
  status: ActionStatus;
  result?: Record<string, any> | null;
  error?: string | null;
  requires_manual_review?: boolean;
  audit?: Record<string, any>;
}

export interface SystemEvent {
  type: "system.event";
  level: SystemEventLevel;
  code: string;
  message: string;
  details?: Record<string, any>;
}

export interface SagaUpdate {
  type: "saga.update";
  session_id: string;
  saga_id: string;
  saga_type?: string | null;
  state: string;
  steps?: Array<Record<string, any>> | null;
  result?: any;
  updated_at?: string | null;
  timestamp?: string;
}

export interface SagaStatusResponse {
  type: "saga.status";
  session_id: string;
  saga_id: string;
  saga_type?: string | null;
  state?: string | null;
  steps?: Array<Record<string, any>> | null;
  result?: any;
  updated_at?: string | null;
  error?: string | null;
  timestamp?: string;
}

export type ServerMessageUnion =
  | ModelPartial
  | ModelFinal
  | ModelInvokeAction
  | ActionResult
  | SystemEvent
  | SagaUpdate
  | SagaStatusResponse;

// ============================================================================
// UNION TYPES FOR MESSAGE HANDLING
// ============================================================================

export type AnyMessage = ClientMessageUnion | ServerMessageUnion;

// ============================================================================
// TYPE GUARDS
// ============================================================================

export function isClientMessage(msg: AnyMessage): msg is ClientMessage {
  return msg.type === "client.message";
}

export function isClientCommand(msg: AnyMessage): msg is ClientCommand {
  return msg.type === "client.command";
}

export function isClientActionConfirm(msg: AnyMessage): msg is ClientActionConfirm {
  return msg.type === "client.action.confirm";
}

export function isActionInvoke(msg: AnyMessage): msg is ActionInvoke {
  return msg.type === "action.invoke";
}

export function isActionConfirm(msg: AnyMessage): msg is ActionConfirm {
  return msg.type === "action.confirm";
}

export function isActionCancel(msg: AnyMessage): msg is ActionCancel {
  return msg.type === "action.cancel";
}

export function isSagaStatusRequest(msg: AnyMessage): msg is SagaStatusRequest {
  return msg.type === "saga.status";
}

export function isModelPartial(msg: AnyMessage): msg is ModelPartial {
  return msg.type === "model.partial";
}

export function isModelFinal(msg: AnyMessage): msg is ModelFinal {
  return msg.type === "model.final";
}

export function isModelInvokeAction(msg: AnyMessage): msg is ModelInvokeAction {
  return msg.type === "model.invoke_action";
}

export function isActionResult(msg: AnyMessage): msg is ActionResult {
  return msg.type === "action.result";
}

export function isSystemEvent(msg: AnyMessage): msg is SystemEvent {
  return msg.type === "system.event";
}

export function isSagaUpdate(msg: AnyMessage): msg is SagaUpdate {
  return msg.type === "saga.update";
}

export function isSagaStatusResponse(msg: AnyMessage): msg is SagaStatusResponse {
  return msg.type === "saga.status";
}

// ============================================================================
// HELPERS
// ============================================================================

/**
 * Serialize a message to JSON string
 */
export function serializeMessage(msg: AnyMessage): string {
  return JSON.stringify(msg);
}

/**
 * Deserialize JSON string to message
 */
export function deserializeMessage(json: string): AnyMessage {
  return JSON.parse(json) as AnyMessage;
}

/**
 * Type-safe message handler
 */
export interface MessageHandler {
  onClientMessage?(msg: ClientMessage): void;
  onClientCommand?(msg: ClientCommand): void;
  onClientActionConfirm?(msg: ClientActionConfirm): void;
  onClientActionInvoke?(msg: ActionInvoke): void;
  onClientActionCancel?(msg: ActionCancel): void;
  onModelPartial?(msg: ModelPartial): void;
  onModelFinal?(msg: ModelFinal): void;
  onModelInvokeAction?(msg: ModelInvokeAction): void;
  onActionResult?(msg: ActionResult): void;
  onSystemEvent?(msg: SystemEvent): void;
  onSagaUpdate?(msg: SagaUpdate): void;
  onSagaStatus?(msg: SagaStatusResponse | SagaStatusRequest): void;
}

/**
 * Dispatch message to appropriate handler
 */
export function dispatchMessage(msg: AnyMessage, handler: MessageHandler): void {
  switch (msg.type) {
    case "client.message":
      handler.onClientMessage?.(msg);
      break;
    case "client.command":
      handler.onClientCommand?.(msg);
      break;
    case "client.action.confirm":
      handler.onClientActionConfirm?.(msg);
      break;
    case "action.invoke":
      handler.onClientActionInvoke?.(msg as ActionInvoke);
      break;
    case "action.confirm":
      handler.onClientActionConfirm?.(msg as any);
      break;
    case "action.cancel":
      handler.onClientActionCancel?.(msg as ActionCancel);
      break;
    case "saga.status":
      handler.onSagaStatus?.(msg as any);
      break;
    case "model.partial":
      handler.onModelPartial?.(msg);
      break;
    case "model.final":
      handler.onModelFinal?.(msg);
      break;
    case "model.invoke_action":
      handler.onModelInvokeAction?.(msg);
      break;
    case "action.result":
      handler.onActionResult?.(msg);
      break;
    case "system.event":
      handler.onSystemEvent?.(msg);
      break;
    case "saga.update":
      handler.onSagaUpdate?.(msg as SagaUpdate);
      break;
    case "saga.status":
      handler.onSagaStatus?.(msg as SagaStatusResponse);
      break;
  }
}
