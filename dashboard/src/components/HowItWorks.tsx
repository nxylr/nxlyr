"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion, useReducedMotion, type Variants } from "framer-motion";
import {
  ArrowRight,
  Check,
  Database,
  FileText,
  PhoneCall,
  RotateCcw,
  Sparkles,
} from "lucide-react";

import { Button } from "@/components/ui/button";

type PipelineStage =
  | "idle"
  | "positioning"
  | "connecting"
  | "calling"
  | "dropped"
  | "retrying"
  | "retryConnecting"
  | "retryCalling"
  | "success"
  | "transcript"
  | "crm"
  | "resolved";

type PipelineNodeProps = {
  description?: string;
  emphasized?: boolean;
  icon?: React.ReactNode;
  label: string;
  pulse?: boolean;
  visible: boolean;
};

const STAGE_TIMINGS_MS: Partial<Record<PipelineStage, number>> = {
  positioning: 1300,
  connecting: 1600,
  calling: 3800,
  dropped: 2500,
  retrying: 1900,
  retryConnecting: 1600,
  retryCalling: 3300,
  success: 1800,
  transcript: 1400,
  crm: 4400,
};

const fanNodes = [
  "Intent clarification",
  "Booking site visit",
  "Answering questions",
  "Clarifying project technicalities",
  "Call drops",
] as const;

const diagramHeight = 820;
const diagramCenterY = diagramHeight / 2;
const fanPathY = [80, 245, 410, 575, 740];
const transcriptPortY = [380, 400, 420, 440];

const nodeEntrance: Variants = {
  hidden: { opacity: 0, scale: 0.92, x: -10 },
  visible: {
    opacity: 1,
    scale: 1,
    x: 0,
    transition: { duration: 0.76, ease: "easeOut" },
  },
};

const fanGroup: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      delayChildren: 0.1,
      staggerChildren: 0.05,
    },
  },
};

function inStage(stage: PipelineStage, ...stages: PipelineStage[]) {
  return stages.includes(stage);
}

function getStageSnapshot(stage: PipelineStage) {
  const fanVisible = inStage(
    stage,
    "calling",
    "dropped",
    "retrying",
    "retryCalling",
    "success",
    "transcript",
    "crm",
    "resolved",
  );
  const fanPulsing = inStage(stage, "calling", "retryCalling");
  const dropped = inStage(stage, "dropped", "retrying");
  const successful = inStage(stage, "success", "transcript", "crm", "resolved");
  const retryActive = inStage(stage, "retrying", "retryConnecting", "retryCalling");

  return {
    agentVisible: !inStage(stage, "idle", "positioning"),
    connectionVisible: !inStage(stage, "idle", "positioning", "retrying"),
    crmVisible: inStage(stage, "crm", "resolved"),
    dropped,
    fallbackGhosted: stage === "resolved",
    fanColor: successful
      ? "var(--secondary)"
      : dropped
        ? "var(--pipeline-drop)"
        : "var(--primary)",
    fanPulsing,
    fanVisible,
    fanConnectionsVisible: fanVisible && stage !== "resolved",
    leadVisible: !inStage(stage, "idle", "positioning"),
    retryActive,
    retryVisible: retryActive || stage === "resolved",
    successful,
    transcriptVisible: inStage(stage, "transcript", "crm", "resolved"),
  };
}

function PipelineNode({
  description,
  emphasized = false,
  icon,
  label,
  pulse = false,
  visible,
}: PipelineNodeProps) {
  return (
    <motion.div
      aria-hidden={!visible}
      variants={nodeEntrance}
      initial="hidden"
      animate={visible ? "visible" : "hidden"}
      className="rounded-xl border px-3 py-3 text-center shadow-sm"
      style={{
        backgroundColor:
          "color-mix(in oklch, var(--brand-base), var(--brand-cream) 5%)",
        borderColor: "var(--pipeline-node-color)",
      }}
    >
      <motion.div
        animate={
          pulse
            ? emphasized
              ? { scale: [1, 1.09, 1], opacity: [0.82, 1, 0.82] }
              : { scale: [1, 1.025, 1], opacity: [0.78, 1, 0.78] }
            : { scale: 1, opacity: 1 }
        }
        transition={
          pulse
            ? {
                duration: emphasized ? 1.44 : 2.24,
                ease: "easeInOut",
                repeat: Number.POSITIVE_INFINITY,
              }
            : { duration: 0.6 }
        }
        className="flex flex-col items-center"
      >
        {icon ? (
          <span
            className="mb-2 grid size-8 place-items-center rounded-lg"
            style={{
              backgroundColor:
                "color-mix(in oklch, var(--pipeline-node-color) 14%, transparent)",
              color: "var(--pipeline-node-color)",
            }}
          >
            {icon}
          </span>
        ) : null}
        <span className="text-sm font-medium leading-5 text-brand-cream sm:text-base">
          {label}
        </span>
        {description ? (
          <span className="mt-1 text-xs leading-4 text-brand-cream/55 sm:text-sm">
            {description}
          </span>
        ) : null}
      </motion.div>
    </motion.div>
  );
}

function AnimatedPath({
  color,
  d,
  markerEnd,
  opacity = 1,
  pulsing = false,
  visible,
  width = 2.5,
}: {
  color: string;
  d: string;
  markerEnd?: string;
  opacity?: number;
  pulsing?: boolean;
  visible: boolean;
  width?: number;
}) {
  return (
    <motion.path
      d={d}
      fill="none"
      markerEnd={markerEnd}
      stroke={color}
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={width}
      initial={false}
      animate={
        visible
          ? pulsing
            ? { opacity: [opacity * 0.42, opacity, opacity * 0.42], pathLength: 1 }
            : { opacity, pathLength: 1 }
          : { opacity: 0, pathLength: 0 }
      }
      transition={
        pulsing
          ? {
              opacity: {
                duration: 2.24,
                ease: "easeInOut",
                repeat: Number.POSITIVE_INFINITY,
              },
              pathLength: { duration: 1.4, ease: "easeInOut" },
            }
          : { duration: 1.4, ease: "easeInOut" }
      }
      vectorEffect="non-scaling-stroke"
    />
  );
}

function LeadNode({ visible }: { visible: boolean }) {
  return (
    <motion.div
      initial={false}
      animate={visible ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.96 }}
      transition={{ duration: 0.5 }}
      className="rounded-xl border border-primary bg-primary px-4 py-3 text-center text-primary-foreground shadow-lg shadow-primary/20"
    >
      <span className="block text-base font-semibold">Trigger a Lead</span>
      <span className="mt-0.5 block text-sm opacity-80">
        Lead comes in · Registered in database
      </span>
      <ArrowRight className="mx-auto mt-2 size-3.5 rotate-90 md:rotate-0" />
    </motion.div>
  );
}

function DesktopPipeline({ stage }: { stage: PipelineStage }) {
  const snapshot = getStageSnapshot(stage);

  return (
    <div className="relative hidden h-[52rem] overflow-hidden rounded-2xl border border-brand-cream/10 bg-brand-base md:block">
      <svg
        aria-hidden="true"
        className="absolute inset-0 h-full w-full"
        preserveAspectRatio="none"
        viewBox={`0 0 1200 ${diagramHeight}`}
      >
        <defs>
          <marker
            id="pipeline-arrow-secondary"
            markerHeight="7"
            markerWidth="7"
            orient="auto"
            refX="6"
            refY="3.5"
          >
            <path d="M0,0 L7,3.5 L0,7 Z" fill="var(--secondary)" />
          </marker>
          <marker
            id="pipeline-arrow-retry"
            markerHeight="7"
            markerWidth="7"
            orient="auto"
            refX="6"
            refY="3.5"
          >
            <path d="M0,0 L7,3.5 L0,7 Z" fill="var(--pipeline-drop)" />
          </marker>
        </defs>

        <AnimatedPath
          color="var(--primary)"
          d={`M198 ${diagramCenterY} L222 ${diagramCenterY}`}
          visible={snapshot.connectionVisible}
        />

        <motion.g
          data-connections="agent-branches"
          initial={false}
          animate={{ opacity: snapshot.fanConnectionsVisible ? 1 : 0 }}
          transition={{ duration: 1.4 }}
        >
          {fanPathY.map((y) => (
            <AnimatedPath
              key={`fan-${y}`}
              color={snapshot.fanColor}
              d={`M438 ${diagramCenterY} C472 ${diagramCenterY} 470 ${y} 504 ${y}`}
              pulsing={snapshot.fanPulsing}
              visible={snapshot.fanVisible}
            />
          ))}
        </motion.g>

        {/* A dropped call never feeds the successful transcript/CRM path. */}
        <g data-connections="successful-convergence">
          {fanPathY.slice(0, -1).map((y, index) => (
            <AnimatedPath
              key={`converge-${y}`}
              color="var(--secondary)"
              d={`M708 ${y} C754 ${y} 768 ${transcriptPortY[index]} 804 ${transcriptPortY[index]}`}
              visible={snapshot.successful}
            />
          ))}
        </g>

        <AnimatedPath
          color="var(--pipeline-drop)"
          d="M708 740 C790 805 430 805 330 500"
          markerEnd="url(#pipeline-arrow-retry)"
          opacity={snapshot.fallbackGhosted ? 0.2 : 1}
          pulsing={snapshot.retryActive}
          visible={snapshot.retryVisible}
          width={3}
        />

        <AnimatedPath
          color="var(--secondary)"
          d={`M996 ${diagramCenterY} L1014 ${diagramCenterY}`}
          markerEnd="url(#pipeline-arrow-secondary)"
          visible={snapshot.crmVisible}
        />
      </svg>

      <div className="absolute left-[1.5%] top-1/2 z-10 w-[15%] -translate-y-1/2">
        <LeadNode visible={snapshot.leadVisible} />
      </div>

      <div className="absolute left-[18.5%] top-1/2 z-10 w-[18%] -translate-y-1/2 [--pipeline-node-color:var(--primary)]">
        <PipelineNode
          icon={<PhoneCall className="size-4" />}
          label="Agent calls the number"
          description={snapshot.retryActive ? "Fresh call attempt" : "Within 60 seconds"}
          pulse={inStage(stage, "connecting", "retryConnecting")}
          visible={snapshot.agentVisible}
        />
      </div>

      <motion.div
        variants={fanGroup}
        initial="hidden"
        animate={snapshot.fanVisible ? "visible" : "hidden"}
      >
        {fanNodes.map((label, index) => {
          const fallbackNode = label === "Call drops";
          const ghosted = fallbackNode && snapshot.fallbackGhosted;

          return (
            <motion.div
              key={label}
              variants={nodeEntrance}
              className="absolute left-[42%] z-10 w-[17%] -translate-y-1/2"
              style={
                {
                  "--pipeline-node-color": ghosted
                    ? "var(--pipeline-drop)"
                    : snapshot.fanColor,
                  top: `${(fanPathY[index] / diagramHeight) * 100}%`,
                } as React.CSSProperties
              }
            >
              <div
                className="transition-opacity duration-700"
                style={{ opacity: ghosted ? 0.24 : 1 }}
              >
                <PipelineNode
                  emphasized={fallbackNode && snapshot.dropped}
                  label={label}
                  pulse={
                    snapshot.fanPulsing ||
                    (fallbackNode && inStage(stage, "dropped", "retrying"))
                  }
                  visible={snapshot.fanVisible}
                />
              </div>
            </motion.div>
          );
        })}
      </motion.div>

      <div className="absolute left-[67%] top-1/2 z-10 w-[16%] -translate-y-1/2 [--pipeline-node-color:var(--secondary)]">
        <PipelineNode
          icon={<FileText className="size-4" />}
          label="Sending transcript"
          description="Call context moves upstream"
          visible={snapshot.transcriptVisible}
        />
      </div>

      <div className="absolute right-[1.5%] top-1/2 z-10 w-[14%] -translate-y-1/2 [--pipeline-node-color:var(--secondary)]">
        <PipelineNode
          icon={<Database className="size-4" />}
          label="Updated CRM"
          description="Ready for human follow-up"
          visible={snapshot.crmVisible}
        />
      </div>

      <motion.div
        initial={false}
        animate={
          snapshot.retryActive || snapshot.fallbackGhosted
            ? { opacity: snapshot.fallbackGhosted ? 0.46 : 1, y: 0 }
            : { opacity: 0, y: 8 }
        }
        transition={{ duration: 0.9 }}
        className="absolute bottom-4 left-[31%] z-10 rounded-full border border-brand-cream/10 bg-brand-base/90 px-3 py-1.5 text-xs text-brand-cream/65"
      >
        {snapshot.fallbackGhosted
          ? "Automatic fallback — not the typical path"
          : "Automatic retry engaged"}
      </motion.div>
    </div>
  );
}

function MobileConnector({
  color,
  opacity = 1,
  pulsing = false,
  visible,
}: {
  color: string;
  opacity?: number;
  pulsing?: boolean;
  visible: boolean;
}) {
  return (
    <motion.div
      aria-hidden="true"
      className="mx-auto h-12 w-0.5 origin-top rounded-full"
      style={{ backgroundColor: color }}
      initial={false}
      animate={
        visible
          ? pulsing
            ? { opacity: [opacity * 0.4, opacity, opacity * 0.4], scaleY: 1 }
            : { opacity, scaleY: 1 }
          : { opacity: 0, scaleY: 0 }
      }
      transition={
        pulsing
          ? { duration: 2.24, ease: "easeInOut", repeat: Number.POSITIVE_INFINITY }
          : { duration: 0.9, ease: "easeInOut" }
      }
    />
  );
}

function MobilePipeline({ stage }: { stage: PipelineStage }) {
  const snapshot = getStageSnapshot(stage);

  return (
    <div className="relative overflow-hidden rounded-2xl border border-brand-cream/10 bg-brand-base px-5 py-8 md:hidden">
      <div className="mx-auto flex max-w-sm flex-col">
        <div className="mx-auto w-full max-w-64">
          <LeadNode visible={snapshot.leadVisible} />
        </div>

        <MobileConnector color="var(--primary)" visible={snapshot.connectionVisible} />

        <div className="mx-auto w-56 [--pipeline-node-color:var(--primary)]">
          <PipelineNode
            icon={<PhoneCall className="size-4" />}
            label="Agent calls the number"
            description={snapshot.retryActive ? "Fresh call attempt" : "Within 60 seconds"}
            pulse={inStage(stage, "connecting", "retryConnecting")}
            visible={snapshot.agentVisible}
          />
        </div>

        <MobileConnector
          color={snapshot.fanColor}
          pulsing={snapshot.fanPulsing}
          visible={snapshot.fanConnectionsVisible}
        />

        <div className="relative">
          {/* The success rail bypasses the fallback row without joining it. */}
          <motion.span
            aria-hidden="true"
            initial={false}
            animate={{ opacity: snapshot.successful ? 1 : 0 }}
            transition={{ duration: 1.4 }}
            className="absolute inset-y-0 right-0 w-px bg-secondary"
          />
          <motion.div
            variants={fanGroup}
            initial="hidden"
            animate={snapshot.fanVisible ? "visible" : "hidden"}
            className="relative space-y-6 px-4"
          >
            <motion.span
              aria-hidden="true"
              initial={false}
              animate={{ opacity: snapshot.fanConnectionsVisible ? 1 : 0 }}
              transition={{ duration: 1.4 }}
              className="absolute inset-y-0 left-0 w-px"
              style={{ backgroundColor: snapshot.fanColor }}
            />
            {fanNodes.map((label) => {
              const fallbackNode = label === "Call drops";
              const ghosted = fallbackNode && snapshot.fallbackGhosted;

              return (
                <motion.div
                  key={label}
                  variants={nodeEntrance}
                  className="relative"
                  style={
                    {
                      "--pipeline-node-color": ghosted
                        ? "var(--pipeline-drop)"
                        : snapshot.fanColor,
                    } as React.CSSProperties
                  }
                >
                  <motion.span
                    aria-hidden="true"
                    data-connection="agent-branch"
                    initial={false}
                    animate={{ opacity: snapshot.fanConnectionsVisible ? 1 : 0 }}
                    transition={{ duration: 1.4 }}
                    className="absolute -left-4 top-1/2 h-px w-4 bg-[var(--pipeline-node-color)]"
                  />
                  {!fallbackNode ? (
                    <motion.span
                      aria-hidden="true"
                      data-connection="successful-convergence"
                      initial={false}
                      animate={{ opacity: snapshot.successful ? 1 : 0 }}
                      transition={{ duration: 1.4 }}
                      className="absolute -right-4 top-1/2 h-px w-4 bg-secondary"
                    />
                  ) : null}
                  <div
                    className="transition-opacity duration-700"
                    style={{ opacity: ghosted ? 0.24 : 1 }}
                  >
                    <PipelineNode
                      emphasized={fallbackNode && snapshot.dropped}
                      label={label}
                      pulse={
                        snapshot.fanPulsing ||
                        (fallbackNode && inStage(stage, "dropped", "retrying"))
                      }
                      visible={snapshot.fanVisible}
                    />
                  </div>
                </motion.div>
              );
            })}
          </motion.div>

          <motion.div
            aria-hidden={!snapshot.retryVisible}
            initial={false}
            animate={
              snapshot.retryVisible
                ? { opacity: snapshot.fallbackGhosted ? 0.46 : 1, x: 0 }
                : { opacity: 0, x: 8 }
            }
            transition={{ duration: 0.9 }}
            className="my-3 flex items-center justify-end gap-2 pr-4 text-sm font-medium text-[var(--pipeline-drop)]"
          >
            <RotateCcw className="size-3.5" />
            {snapshot.fallbackGhosted
              ? "Automatic fallback — not the typical path"
              : "Retrying the call automatically"}
          </motion.div>
        </div>

        <motion.div
          aria-hidden="true"
          initial={false}
          animate={{ opacity: snapshot.successful ? 1 : 0 }}
          transition={{ duration: 1.4 }}
          className="relative h-12"
        >
          <span className="absolute right-0 top-0 h-6 w-1/2 rounded-br-xl border-b border-r border-secondary" />
          <span className="absolute left-1/2 top-6 h-6 border-l border-secondary" />
        </motion.div>

        <div className="mx-auto w-52 [--pipeline-node-color:var(--secondary)]">
          <PipelineNode
            icon={<FileText className="size-4" />}
            label="Sending transcript"
            description="Call context moves upstream"
            visible={snapshot.transcriptVisible}
          />
        </div>

        <MobileConnector color="var(--secondary)" visible={snapshot.crmVisible} />

        <div className="mx-auto w-48 [--pipeline-node-color:var(--secondary)]">
          <PipelineNode
            icon={<Database className="size-4" />}
            label="Updated CRM"
            description="Ready for human follow-up"
            visible={snapshot.crmVisible}
          />
        </div>
      </div>
    </div>
  );
}

function TriggerGate({
  entered,
  onStart,
  positioning,
}: {
  entered: boolean;
  onStart: () => void;
  positioning: boolean;
}) {
  const button = (
    <Button
      size="lg"
      onClick={onStart}
      disabled={positioning}
      className="h-12 rounded-xl px-5 shadow-xl shadow-primary/25"
    >
      <Sparkles data-icon="inline-start" />
      Trigger a Lead
    </Button>
  );

  return (
    <>
      <motion.div
        aria-hidden="true"
        initial={false}
        animate={{ opacity: positioning ? 0 : 1 }}
        transition={{ duration: 1.1 }}
        className="pointer-events-none absolute inset-0 z-20 rounded-2xl bg-brand-base/10 backdrop-blur-[8px]"
      />

      <motion.div
        initial={false}
        animate={
          positioning
            ? { left: "9%", opacity: 1, scale: 0.94 }
            : { left: "50%", opacity: entered ? 1 : 0, scale: 1 }
        }
        transition={{ duration: 1.2, ease: [0.22, 1, 0.36, 1] }}
        className="absolute top-1/2 z-30 hidden -translate-x-1/2 -translate-y-1/2 md:block"
      >
        {button}
      </motion.div>

      <motion.div
        initial={false}
        animate={
          positioning
            ? { opacity: 1, scale: 0.94, top: "6rem" }
            : { opacity: entered ? 1 : 0, scale: 1, top: "50%" }
        }
        transition={{ duration: 1.2, ease: [0.22, 1, 0.36, 1] }}
        className="absolute left-1/2 top-1/2 z-30 -translate-x-1/2 -translate-y-1/2 md:hidden"
      >
        {button}
      </motion.div>
    </>
  );
}

function getNextStage(stage: PipelineStage, shouldDrop: boolean): PipelineStage | null {
  switch (stage) {
    case "positioning":
      return "connecting";
    case "connecting":
      return "calling";
    case "calling":
      return shouldDrop ? "dropped" : "success";
    case "dropped":
      return "retrying";
    case "retrying":
      return "retryConnecting";
    case "retryConnecting":
      return "retryCalling";
    case "retryCalling":
      return "success";
    case "success":
      return "transcript";
    case "transcript":
      return "crm";
    case "crm":
      return "resolved";
    default:
      return null;
  }
}

export function HowItWorks() {
  const [stage, setStage] = useState<PipelineStage>("idle");
  const [hasEnteredViewport, setHasEnteredViewport] = useState(false);
  const diagramRef = useRef<HTMLDivElement>(null);
  const firstPlayStartedRef = useRef(false);
  const shouldDropRef = useRef(true);
  const replayTimerRef = useRef<number | null>(null);
  const shouldReduceMotion = useReducedMotion();
  const renderedStage: PipelineStage =
    shouldReduceMotion ? "resolved" : stage;
  const diagramStage = renderedStage === "idle" ? "resolved" : renderedStage;
  const gateVisible = !shouldReduceMotion && inStage(stage, "idle", "positioning");

  const startSequence = useCallback(() => {
    shouldDropRef.current = firstPlayStartedRef.current
      ? Math.random() < 0.5
      : true;
    firstPlayStartedRef.current = true;
    setStage(shouldReduceMotion ? "resolved" : "positioning");
  }, [shouldReduceMotion]);

  const replaySequence = useCallback(() => {
    setStage("idle");
    replayTimerRef.current = window.setTimeout(startSequence, 840);
  }, [startSequence]);

  useEffect(() => {
    const diagram = diagramRef.current;
    if (!diagram || hasEnteredViewport) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        setHasEnteredViewport(true);
        observer.disconnect();
        // Start once on entry. A manual start before this callback must not
        // restart the run or randomize the scripted first outcome.
        if (!firstPlayStartedRef.current) startSequence();
      },
      { rootMargin: "0px 0px -12%", threshold: 0.1 },
    );

    observer.observe(diagram);
    return () => observer.disconnect();
  }, [hasEnteredViewport, startSequence]);

  useEffect(() => {
    if (shouldReduceMotion || stage === "idle" || stage === "resolved") return;

    const nextStage = getNextStage(stage, shouldDropRef.current);
    const delay = STAGE_TIMINGS_MS[stage];
    if (!nextStage || delay === undefined) return;

    const timer = window.setTimeout(() => setStage(nextStage), delay);
    return () => window.clearTimeout(timer);
  }, [shouldReduceMotion, stage]);

  useEffect(
    () => () => {
      if (replayTimerRef.current !== null) {
        window.clearTimeout(replayTimerRef.current);
      }
    },
    [],
  );

  return (
    <section
      id="pipeline"
      className="scroll-mt-20 bg-card py-16 sm:py-20"
    >
      <div className="mx-auto max-w-6xl px-6 lg:px-8">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-base font-medium text-primary">How the pipeline works</p>
            <h2 className="mt-3 max-w-2xl text-4xl font-semibold tracking-[-0.045em] text-foreground sm:text-5xl">
              Follow one lead from trigger to an updated CRM.
            </h2>
          </div>
          <p className="max-w-sm text-base leading-7 text-muted-foreground">
            The first run is scripted to show how the agent recovers when a call drops.
          </p>
        </div>

        <div ref={diagramRef} className="relative mt-10" aria-live="polite">
          <span className="sr-only">Pipeline state: {renderedStage}</span>
          <DesktopPipeline stage={diagramStage} />
          <MobilePipeline stage={diagramStage} />

          {gateVisible ? (
            <TriggerGate
              entered={hasEnteredViewport}
              onStart={startSequence}
              positioning={stage === "positioning"}
            />
          ) : null}
        </div>

        <motion.div
          initial={false}
          animate={
            renderedStage === "resolved" && (shouldReduceMotion || stage !== "idle")
              ? { opacity: 1, pointerEvents: "auto", y: 0 }
              : { opacity: 0, y: 8, pointerEvents: "none" }
          }
          transition={{ duration: shouldReduceMotion ? 0 : 0.7 }}
          className="mt-6 flex justify-center"
        >
          <Button variant="outline" onClick={replaySequence}>
            {shouldReduceMotion ? <Check /> : <RotateCcw />}
            Experience the pipeline again
          </Button>
        </motion.div>
      </div>
    </section>
  );
}
