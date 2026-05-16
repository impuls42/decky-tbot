import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { useEffect, useRef, useState } from "react";
import { FaTree } from "react-icons/fa";

type Status = {
  unit: string;
  load_state: string;
  active_state: string;
  sub_state: string;
  result: string;
  unit_file_state: string;
  ok: boolean;
};

type ActionResult = { ok: boolean; error: string };

type AgentState = {
  mode?: string;
  goal?: string;
  ready?: boolean;
  pendingRequest?: { id: string; prompt: string; createdAt: string } | null;
  agentStatus?: string;
  lastError?: string | null;
};

type ModStatus = {
  ok: boolean;
  endpoint: string;
  ping: { status: string; ready: boolean } | null;
  ping_error: string | null;
  agent_state: AgentState | null;
  agent_auth_failed: boolean;
  agent_error: string | null;
  has_auth_token: boolean;
};

type Logs = { ok: boolean; lines: string[]; error: string };

const getUnitStatus = callable<[], Status>("get_unit_status");
const startUnit = callable<[], ActionResult>("start_unit");
const stopUnit = callable<[], ActionResult>("stop_unit");
const restartUnit = callable<[], ActionResult>("restart_unit");
const getModStatus = callable<[], ModStatus>("get_mod_status");
const getUnitLogs = callable<[number], Logs>("get_unit_logs");

const POLL_MS = 2000;

const COLOR_GREEN = "#3fb950";
const COLOR_RED = "#f85149";
const COLOR_YELLOW = "#d29922";
const COLOR_GREY = "#888";

function unitColor(s: Status | undefined): string {
  if (!s) return COLOR_GREY;
  if (s.active_state === "active") return COLOR_GREEN;
  if (s.active_state === "failed" || s.active_state === "inactive") return COLOR_RED;
  return COLOR_YELLOW;
}

type Pill = { label: string; color: string };

function modPill(m: ModStatus | undefined): Pill {
  if (!m) return { label: "loading…", color: COLOR_GREY };
  if (!m.ok) return { label: "Disconnected", color: COLOR_RED };
  if (m.agent_auth_failed)
    return { label: "Connected · auth required", color: COLOR_GREY };
  const state = m.agent_state;
  if (!state) return { label: "Connected · Not Ready", color: COLOR_YELLOW };
  if (!state.ready) return { label: "Connected · Not Ready", color: COLOR_YELLOW };
  if (state.pendingRequest)
    return { label: "Connected · Ready · Running", color: COLOR_GREEN };
  return { label: "Connected · Ready · Idle", color: COLOR_GREEN };
}

function Dot({ color }: { color: string }) {
  return (
    <span
      style={{
        width: 10,
        height: 10,
        borderRadius: 5,
        background: color,
        display: "inline-block",
        flexShrink: 0,
      }}
    />
  );
}

function Content() {
  const [status, setStatus] = useState<Status | undefined>();
  const [mod, setMod] = useState<ModStatus | undefined>();
  const [logs, setLogs] = useState<Logs | undefined>();
  const [logsOpen, setLogsOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const logsOpenRef = useRef(logsOpen);
  logsOpenRef.current = logsOpen;

  const refresh = async () => {
    try {
      const [s, m] = await Promise.all([getUnitStatus(), getModStatus()]);
      setStatus(s);
      setMod(m);
      if (logsOpenRef.current) {
        try {
          setLogs(await getUnitLogs(20));
        } catch (e) {
          console.error("get_unit_logs failed", e);
        }
      }
    } catch (e) {
      console.error("refresh failed", e);
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (logsOpen) {
      getUnitLogs(20).then(setLogs).catch((e) => console.error(e));
    }
  }, [logsOpen]);

  const run = async (label: string, fn: () => Promise<ActionResult>) => {
    setBusy(true);
    try {
      const r = await fn();
      if (!r.ok) {
        toaster.toast({
          title: `${label} failed`,
          body: r.error || "unknown error",
        });
      }
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const unitState = status
    ? `${status.active_state}${status.sub_state ? ` (${status.sub_state})` : ""}${
        status.active_state === "failed" && status.result
          ? ` — ${status.result}`
          : ""
      }`
    : "loading…";

  const pill = modPill(mod);
  const endpoint = mod?.endpoint ?? "—";

  return (
    <PanelSection title="Timberbot connector">
      <PanelSectionRow>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "4px 0",
          }}
        >
          <Dot color={unitColor(status)} />
          <span>tbot-watch.service · {unitState}</span>
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "4px 0",
          }}
        >
          <Dot color={pill.color} />
          <span>
            mod · {endpoint} · {pill.label}
          </span>
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={busy || status?.active_state === "active"}
          onClick={() => run("Start", startUnit)}
        >
          Start
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={busy || status?.active_state !== "active"}
          onClick={() => run("Stop", stopUnit)}
        >
          Stop
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={busy}
          onClick={() => run("Restart", restartUnit)}
        >
          Restart
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={() => setLogsOpen((v) => !v)}
        >
          {logsOpen ? "Hide logs" : "Show logs (last 20)"}
        </ButtonItem>
      </PanelSectionRow>
      {logsOpen && (
        <PanelSectionRow>
          <pre
            style={{
              maxHeight: 180,
              overflowY: "auto",
              fontSize: 11,
              lineHeight: 1.3,
              margin: 0,
              padding: 6,
              background: "rgba(0,0,0,0.35)",
              borderRadius: 4,
              whiteSpace: "pre-wrap",
              wordBreak: "break-all",
            }}
          >
            {logs && logs.lines.length > 0
              ? logs.lines.join("\n")
              : logs && !logs.ok
                ? logs.error || "journalctl failed"
                : "loading…"}
          </pre>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

export default definePlugin(() => ({
  name: "Timberbot Connector",
  titleView: (
    <div className={staticClasses.Title}>Timberbot Connector</div>
  ),
  content: <Content />,
  icon: <FaTree />,
  onDismount() {},
}));
