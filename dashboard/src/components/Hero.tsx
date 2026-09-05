"use client";

import {
  type CSSProperties,
  type FormEvent,
  type MouseEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowRight, PhoneCall, Signal, Wifi } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  demoCallUrl,
  type DemoCallMessage,
  normalizeIndianNumber,
  requestDemoCall,
} from "@/lib/demoCall";

type PhoneStyle = CSSProperties & {
  "--phone-rotate-x": string;
  "--phone-rotate-y": string;
};

export function Hero() {
  const [phone, setPhone] = useState("");
  const [message, setMessage] = useState<DemoCallMessage | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isFormVisible, setIsFormVisible] = useState(false);
  const [canTilt, setCanTilt] = useState(false);
  const shouldReduceMotion = useReducedMotion();
  const phoneInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)");
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

    function updateTiltPreference() {
      setCanTilt(finePointer.matches && !reducedMotion.matches);
    }

    updateTiltPreference();
    finePointer.addEventListener("change", updateTiltPreference);
    reducedMotion.addEventListener("change", updateTiltPreference);

    return () => {
      finePointer.removeEventListener("change", updateTiltPreference);
      reducedMotion.removeEventListener("change", updateTiltPreference);
    };
  }, []);

  useEffect(() => {
    if (isFormVisible) phoneInput.current?.focus();
  }, [isFormVisible]);

  function openDemo() {
    setIsFormVisible(true);
  }

  function handlePhoneMove(event: MouseEvent<HTMLDivElement>) {
    if (!canTilt) return;

    const bounds = event.currentTarget.getBoundingClientRect();
    const relativeX = (event.clientX - bounds.left) / bounds.width - 0.5;
    const relativeY = (event.clientY - bounds.top) / bounds.height - 0.5;
    const rotateY = Math.max(-4, Math.min(4, relativeX * 8));
    const rotateX = Math.max(-4, Math.min(4, relativeY * -8));

    event.currentTarget.style.setProperty("--phone-rotate-x", `${rotateX}deg`);
    event.currentTarget.style.setProperty("--phone-rotate-y", `${rotateY}deg`);
  }

  function resetPhoneTilt(event: MouseEvent<HTMLDivElement>) {
    event.currentTarget.style.setProperty("--phone-rotate-x", "0deg");
    event.currentTarget.style.setProperty("--phone-rotate-y", "0deg");
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);

    const normalizedPhone = normalizeIndianNumber(phone);
    if (!normalizedPhone) {
      setMessage({
        text: "Enter a valid 10-digit Indian mobile number.",
        type: "error",
      });
      phoneInput.current?.focus();
      return;
    }

    setPhone(normalizedPhone);
    setIsSubmitting(true);

    try {
      const result = await requestDemoCall(normalizedPhone);
      setMessage(result);

      if (result.resetForm) setPhone("");
      if (result.focusPhoneInput) phoneInput.current?.focus();
    } finally {
      setIsSubmitting(false);
    }
  }

  const phoneStyle: PhoneStyle = {
    "--phone-rotate-x": "0deg",
    "--phone-rotate-y": "0deg",
  };

  return (
    <section
      id="hero"
      className="relative flex min-h-[100svh] items-center overflow-hidden bg-background px-6 py-16"
    >
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 flex select-none items-center justify-center overflow-hidden">
        <span className="hero-watermark font-serif text-[clamp(7rem,24vw,28rem)] leading-none tracking-[-0.08em] text-primary/[0.07] blur-[2px]">
          NXLYR
        </span>
      </div>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-1/2 h-72 w-72 -translate-x-1/2 -translate-y-1/2 rounded-full bg-muted/60 blur-3xl sm:h-96 sm:w-96"
      />

      <div className="relative z-10 mx-auto grid w-full max-w-[90rem] items-center gap-12 lg:grid-cols-[minmax(0,1fr)_clamp(18rem,30vw,24rem)_minmax(0,1fr)] lg:gap-8 xl:gap-12">
        <div className="mx-auto w-full max-w-2xl">
          <p className="flex items-center gap-3 text-xs font-medium uppercase tracking-[0.2em] text-primary sm:text-sm">
            <span aria-hidden="true" className="h-px w-8 shrink-0 bg-border" />
            A real conversation, on your phone
          </p>
          <h1 className="mt-6 font-serif text-5xl font-normal leading-[1.05] tracking-[-0.045em] text-foreground sm:text-6xl xl:text-7xl">
            Respond while buyer intent is <em className="font-normal text-primary">still high</em>
          </h1>
          <div className="mt-7 flex items-start gap-3 border-t border-border/60 pt-5 text-primary">
            <span aria-hidden="true" className="relative mt-1 inline-flex size-3 shrink-0">
              <span className="absolute inset-0 rounded-full bg-primary/35 motion-safe:animate-ping" />
              <span className="relative size-3 rounded-full bg-primary" />
            </span>
            <p className="text-xs font-medium uppercase tracking-[0.16em] sm:text-sm">
              System Active<span className="sr-only"> — </span>
              <span className="mt-1.5 block text-[0.65rem] tracking-[0.2em] sm:text-xs">Inbound Routing</span>
            </p>
          </div>
        </div>

        <div className="flex min-w-0 flex-col items-center">
          <div className="relative">
            <AnimatePresence initial={false}>
              {!isFormVisible ? (
                <motion.span
                  aria-hidden="true"
                  initial={{ opacity: 0, scale: 0.98 }}
                  animate={shouldReduceMotion ? { opacity: 1, scale: 1 } : { opacity: [0.48, 0.95, 0.48], scale: [1, 1.075, 1] }}
                  exit={{ opacity: 0, scale: 1.1 }}
                  transition={{ duration: shouldReduceMotion ? 0 : 2.1, ease: "easeInOut", repeat: shouldReduceMotion ? 0 : Infinity }}
                  className="pointer-events-none absolute -inset-4 rounded-[clamp(3.4rem,6vw,4.7rem)] border border-border/60 bg-muted/10"
                />
              ) : null}
            </AnimatePresence>

            <div
              id="demo"
              onClick={() => {
                if (!isFormVisible) openDemo();
              }}
              onMouseMove={handlePhoneMove}
              onMouseLeave={resetPhoneTilt}
              style={phoneStyle}
              className="phone-tilt relative w-[clamp(18rem,30vw,24rem)] cursor-pointer rounded-[clamp(2.7rem,5vw,3.8rem)] border border-foreground/15 bg-gradient-to-br from-foreground via-brand-base to-foreground p-[clamp(0.55rem,1vw,0.8rem)] shadow-[0_30px_70px_-30px_color-mix(in_oklch,var(--brand-base)_70%,transparent)]"
            >
            <div className="flex aspect-[9/18.5] flex-col overflow-hidden rounded-[clamp(2.15rem,4.2vw,3rem)] border border-brand-cream/10 bg-brand-base p-[clamp(0.9rem,2vw,1.35rem)] text-brand-cream">
              <div className="flex items-center justify-between text-[clamp(0.55rem,1vw,0.7rem)] text-brand-cream/70">
                <span>09:41</span>
                <span className="flex items-center gap-1">
                  <Signal className="size-[clamp(0.65rem,1.2vw,0.85rem)]" />
                  <Wifi className="size-[clamp(0.65rem,1.2vw,0.85rem)]" />
                </span>
              </div>

              <AnimatePresence initial={false} mode="wait">
                {isFormVisible ? (
                  <motion.div
                    key="phone-form"
                    id="demo-call-panel"
                    initial={{ opacity: 0, x: 18 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: -18 }}
                    transition={{ duration: 0.28, ease: "easeOut" }}
                    className="flex min-h-0 flex-1 flex-col justify-center"
                  >
                    <div className="mb-[clamp(0.8rem,2vw,1.25rem)]">
                      <p className="text-[clamp(1rem,1.6vw,1.15rem)] font-medium">
                        Try the live demo
                      </p>
                      <p className="mt-1 text-[clamp(0.72rem,1.2vw,0.88rem)] leading-5 text-brand-cream/55">
                        A real call, usually within 60 seconds.
                      </p>
                    </div>

                    <form
                      action={demoCallUrl}
                      method="post"
                      noValidate
                      onSubmit={handleSubmit}
                    >
                      <label
                        className="mb-2 block text-[clamp(0.75rem,1.3vw,0.9rem)] font-medium text-brand-cream/80"
                        htmlFor="phone"
                      >
                        Indian mobile number
                      </label>
                      <Input
                        ref={phoneInput}
                        id="phone"
                        name="phone"
                        type="tel"
                        inputMode="tel"
                        autoComplete="tel"
                        placeholder="98765 43210"
                        aria-describedby="form-message consent"
                        required
                        value={phone}
                        onChange={(event) => setPhone(event.target.value)}
                        className="h-[clamp(2.6rem,4vw,3rem)] border-brand-cream/20 bg-brand-cream/8 px-3 text-[clamp(0.9rem,1.6vw,1.08rem)] text-brand-cream shadow-none placeholder:text-brand-cream/35 focus-visible:border-primary focus-visible:ring-primary/25"
                      />
                      <Button
                        type="submit"
                        disabled={isSubmitting}
                        className="mt-3 h-[clamp(2.6rem,4vw,3rem)] w-full rounded-md bg-primary px-4 text-[clamp(0.85rem,1.4vw,1rem)] text-primary-foreground hover:bg-primary/90"
                      >
                        {isSubmitting ? "Requesting call…" : "Call me now"}
                      </Button>
                    </form>

                    {message ? (
                      <p
                        id="form-message"
                        className={`mt-3 border-l-2 pl-2 text-[clamp(0.7rem,1.1vw,0.82rem)] leading-4 ${
                          message.type === "success"
                            ? "border-secondary text-brand-cream/75"
                            : "border-primary text-brand-cream/75"
                        }`}
                        role="status"
                        aria-live="polite"
                      >
                        {message.text}
                      </p>
                    ) : null}
                  </motion.div>
                ) : (
                  <motion.button
                    key="phone-idle"
                    type="button"
                    aria-expanded={isFormVisible}
                    aria-controls="demo-call-panel"
                    aria-label="Open the live phone call demo"
                    onClick={openDemo}
                    initial={{ opacity: 0, x: -18 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: 18 }}
                    transition={{ duration: 0.28, ease: "easeOut" }}
                    className="flex min-h-0 flex-1 cursor-pointer flex-col items-center justify-center text-center outline-none focus-visible:ring-4 focus-visible:ring-primary/30"
                  >
                    <span className="grid size-[clamp(3.6rem,7vw,5rem)] place-items-center rounded-full bg-primary text-primary-foreground shadow-lg">
                      <PhoneCall className="size-[clamp(1.4rem,3vw,2rem)]" />
                    </span>
                    <span className="mt-5 font-serif text-[clamp(1.4rem,2.5vw,1.8rem)]">
                      Try a real call
                    </span>
                    <span className="mt-1.5 text-[clamp(0.72rem,1.2vw,0.9rem)] leading-5 text-brand-cream/55">
                      Tap to test conversational AI
                    </span>
                  </motion.button>
                )}
              </AnimatePresence>
            </div>
            <span className="pointer-events-none absolute inset-x-0 -bottom-1 mx-auto h-2 w-24 rounded-full bg-foreground/25 blur-sm" />
            </div>
          </div>

          <p
            id="consent"
            className="mt-5 max-w-sm text-center text-sm leading-6 text-muted-foreground"
          >
            By submitting your number, you consent to receiving an AI-generated demonstration call. This is a demo — no real property transaction is involved.
          </p>
        </div>

        <div className="mx-auto w-full max-w-2xl lg:text-right">
          <p className="max-w-xl font-serif text-2xl leading-snug text-muted-foreground lg:ml-auto sm:text-3xl">
            Lead intent drops sharply after five minutes without contact. NXLYR lets a prospect hear from you while their enquiry still has momentum.
          </p>
          <dl className="mt-7 border-t border-border/60 pt-5 lg:ml-auto">
            {/* The proposed <650ms claim is withheld: agent/week2_latency.csv
                records 60 round trips with a 1781.8ms median. Add a latency
                callout only after a representative benchmark supports it. */}
            <div className="flex flex-col gap-2">
              <dt className="order-2 text-xs uppercase tracking-[0.1em] text-primary sm:text-sm">Instant inbound pickup</dt>
              <dd className="font-serif text-3xl text-foreground sm:text-4xl">24/7/365</dd>
            </div>
          </dl>
          <AnimatePresence initial={false}>
            {!isFormVisible ? (
              <motion.div
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.24, ease: "easeOut" }}
                className="lg:flex lg:justify-end"
              >
                <Button
                  type="button"
                  onClick={openDemo}
                  className="mt-8 h-12 max-w-full rounded-full bg-primary px-5 text-sm text-primary-foreground shadow-lg shadow-primary/25 hover:bg-primary/90 xl:text-base"
                >
                  Start Live Call Demo
                  <ArrowRight aria-hidden="true" className="size-4" />
                </Button>
              </motion.div>
            ) : null}
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
}
