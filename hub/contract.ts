export type ProcessStatus = {
  state: 'stopped' | 'starting' | 'running' | 'stopping' | 'failed';
  error: string | null;
  session: number;
};

export type Settings = {
  backend: 'fake' | 'luna';
  python: string;
  bun: string;
  db: string;
};

export type HubEvent = {
  sequence: number;
  event_id: string;
  turn_id: string | null;
  kind: string;
  source: string | null;
  occurred_at: string;
  text: string;
  action: string | null;
};

export type RuntimeSnapshot = {
  runtime: { state: 'idle' | 'generating' | 'failed'; turn_id: string | null };
  model: { name: string; reasoning: string | null; bridge: string };
  perception: { id: string; kind: string; source: string; occurred_at: string } | null;
  wake: { decision: boolean | null; reason: string | null };
  live_state: { kind: string; source: string; text: string; expires_in_seconds: number }[];
  context: {
    turn_id: string | null;
    frame_bytes: number | null;
    history_turns: number | null;
    sensor_included: boolean | null;
    older_history_omitted: boolean | null;
  };
  generation: {
    turn_id: string | null;
    first_tool_delta_ms: number | null;
    duration_ms: number | null;
    bridge_duration_ms: number | null;
    usage: Record<string, number> | null;
    last_action: string | null;
  };
  errors: { code: string; turn_id: string } | null;
};

export type Inspection = { snapshot: RuntimeSnapshot; activity: HubEvent[]; dialogue: HubEvent[] };

export type RuntimeOutput = {
  kind: string;
  character_id: string;
  revision: number;
  turn_id: string | null;
  text: string;
  delta_index: number;
};

export type Control = 'start' | 'stop' | 'restart';
export type ControlResult = ProcessStatus & { inspection?: Inspection };

export interface HubAPI {
  status(): Promise<ProcessStatus>;
  settings(): Promise<Settings>;
  saveSettings(settings: Settings): Promise<Settings>;
  control(action: Control): Promise<ControlResult>;
  inspect(): Promise<Inspection>;
  sendChat(text: string): Promise<{ turn_id: string }>;
  setScene(text: string): Promise<null>;
  onStatus(listener: (status: ProcessStatus) => void): () => void;
  onOutput(listener: (output: RuntimeOutput, session: number) => void): () => void;
}

declare global {
  interface Window {
    hub: HubAPI;
  }
}
