export type AgentID =
  | "orchestrator"
  | "market-intel"
  | "forecasting"
  | "optimization"
  | "execution"
  | "settlement"
  | "risk";

export type MessageType = "REQUEST" | "RESULT" | "EVENT" | "HALT";
export type Priority = "RT" | "DA" | "BATCH";

export type EventType =
  | "PRICE_ANOMALY"
  | "OUTAGE_DETECTED"
  | "RISK_BREACH"
  | "HALT"
  | "FORECAST_READY"
  | "DISPATCH_READY"
  | "SETTLEMENT_DISCREPANCY";

export interface AgentMessage<T = unknown> {
  id: string;
  type: MessageType;
  from: AgentID;
  to: AgentID | "broadcast";
  timestamp: string;
  priority: Priority;
  traceId: string;
  payload: T;
}

export interface PriceAnomalyPayload {
  iso: ISO;
  node: string;
  sigma: number;
  currentPrice: number;
  historicalMean: number;
  context: string;
}

export interface HaltPayload {
  reason: string;
  severity: "WARNING" | "STOP" | "EMERGENCY";
  initiatedBy: AgentID;
}

export type ISO = "ERCOT" | "PJM" | "CAISO" | "ISONE" | "MISO" | "NYISO" | "SPP";

export type Market = "DA_ENERGY" | "RT_ENERGY" | "REG_UP" | "REG_DOWN" | "SPIN" | "NONSPIN";
