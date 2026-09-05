"use client";

import { motion } from "framer-motion";
import {
  BadgeCheck,
  Building2,
  Clock3,
  Droplet,
  Phone,
  PhoneOff,
  UserPlus,
  UserRound,
} from "lucide-react";

import { ArchitecturalBackdrop } from "@/components/ArchitecturalBackdrop";

type ProblemKind = "response" | "parallel" | "leak" | "scale";

const problems: Array<{
  description: string;
  kind: ProblemKind;
  title: string;
}> = [
  {
    kind: "response",
    title: "No instant response",
    description:
      "Average developer callback times run from 15–240 minutes, even though lead intent drops sharply after five minutes without contact.",
  },
  {
    kind: "parallel",
    title: "Human callers can’t parallelize",
    description:
      "One pre-sales agent can only be on one call at a time. Every other fresh lead waits for that conversation to finish.",
  },
  {
    kind: "leak",
    title: "Data leaks to brokers",
    description:
      "Leads have been documented reaching competing developers and brokers before the original developer’s own team calls back.",
  },
  {
    kind: "scale",
    title: "Scaling a team is slow and expensive",
    description:
      "Hiring and training pre-sales staff takes real time and money before a single additional call can be made.",
  },
];

function ProblemIllustration({ kind }: { kind: ProblemKind }) {
  if (kind === "response") {
    return (
      <div className="relative grid h-20 place-items-center overflow-hidden rounded-lg border border-brand-cream/10 bg-brand-cream/[0.025]">
        <motion.div
          whileInView={{ rotate: [0, -9, 9, -6, 6, 0] }}
          whileHover={{ rotate: [0, -9, 9, -6, 6, 0] }}
          viewport={{ once: true, amount: 0.7 }}
          transition={{ duration: 0.8, ease: "easeInOut" }}
          className="grid size-8 place-items-center rounded-full border border-primary/35 bg-primary/10 text-primary"
        >
          <PhoneOff className="size-4" />
        </motion.div>
        <Clock3 className="absolute right-4 top-4 size-4 text-brand-cream/35" />
      </div>
    );
  }

  if (kind === "parallel") {
    return (
      <div className="relative flex h-20 items-center justify-center gap-5 overflow-hidden rounded-lg border border-brand-cream/10 bg-brand-cream/[0.025]">
        <motion.span
          whileHover={{ scale: 1.08 }}
          className="grid size-8 place-items-center rounded-full border border-secondary/40 bg-secondary/15 text-secondary"
        >
          <UserRound className="size-4" />
        </motion.span>
        <div className="flex gap-2">
          {[0, 1, 2].map((index) => (
            <motion.span
              key={index}
              initial={{ opacity: 0.25, scale: 0.85 }}
              whileInView={{ opacity: [0.25, 0.9, 0.25], scale: [0.85, 1, 0.85] }}
              viewport={{ once: true, amount: 0.7 }}
              transition={{ delay: index * 0.16, duration: 1.2 }}
              className="grid size-7 place-items-center rounded-full border border-primary/30 text-primary/70"
            >
              <Phone className="size-3" />
            </motion.span>
          ))}
        </div>
      </div>
    );
  }

  if (kind === "leak") {
    return (
      <div className="relative grid h-20 place-items-center overflow-hidden rounded-lg border border-brand-cream/10 bg-brand-cream/[0.025]">
        <div className="grid size-8 place-items-center rounded-md border border-primary/35 bg-primary/10 text-primary">
          <Building2 className="size-4" />
        </div>
        <motion.span
          initial={{ opacity: 0, y: -5 }}
          whileInView={{ opacity: [0, 0.9, 0], y: [-5, 12, 22] }}
          whileHover={{ opacity: [0, 0.9, 0], y: [-5, 12, 22] }}
          viewport={{ once: true, amount: 0.7 }}
          transition={{ duration: 1.25, ease: "easeIn" }}
          className="absolute bottom-4 right-[34%] text-primary"
        >
          <Droplet className="size-4 fill-current" />
        </motion.span>
      </div>
    );
  }

  return (
    <div className="relative flex h-20 items-end justify-center gap-2 overflow-hidden rounded-lg border border-brand-cream/10 bg-brand-cream/[0.025] pb-4">
      {[0.55, 0.75, 1].map((scale, index) => (
        <motion.span
          key={scale}
          initial={{ scaleY: 0.25 }}
          whileInView={{ scaleY: scale }}
          whileHover={{ scaleY: 1 }}
          viewport={{ once: true, amount: 0.7 }}
          transition={{ delay: index * 0.12, duration: 0.55, ease: "easeOut" }}
          className="h-8 w-2.5 origin-bottom rounded-t-sm bg-secondary/55"
        />
      ))}
      <UserPlus className="ml-2 size-4 text-primary" />
    </div>
  );
}

export function WhyThisMatters() {
  return (
    <section
      id="why-we-do-it"
      className="relative scroll-mt-20 overflow-hidden bg-brand-base py-16 text-brand-cream sm:py-20"
    >
      <ArchitecturalBackdrop variant="section" />
      <div className="relative z-10 mx-auto max-w-6xl px-6 lg:px-8">
        <p className="text-base font-medium text-primary">Why we do it</p>
        <h2 className="mt-3 max-w-2xl text-4xl font-semibold tracking-[-0.045em] sm:text-5xl">
          Waiting is expensive when interest is fresh.
        </h2>

        <div className="mt-10 grid gap-4 sm:grid-cols-2">
          {problems.map((problem, index) => (
            <motion.article
              key={problem.title}
              initial={{ opacity: 0, y: 14 }}
              whileInView={{ opacity: 1, y: 0 }}
              whileHover={{ y: -3 }}
              viewport={{ once: true, amount: 0.3 }}
              transition={{ delay: index * 0.06, duration: 0.42, ease: "easeOut" }}
              className="rounded-xl border border-brand-cream/20 bg-brand-base p-5"
            >
              <ProblemIllustration kind={problem.kind} />
              <h3 className="mt-4 text-xl font-semibold text-brand-cream">{problem.title}</h3>
              <p className="mt-2 text-lg leading-8 text-brand-cream/75">
                {problem.description}
              </p>
            </motion.article>
          ))}
        </div>

        <div className="mt-12 grid gap-px overflow-hidden rounded-xl border border-brand-cream/10 bg-brand-cream/10 sm:grid-cols-3">
          {[
            { icon: Building2, label: "Built for Indian real estate" },
            { icon: BadgeCheck, label: "DPDP-compliant" },
            { icon: Phone, label: "Live on real phone lines" },
          ].map(({ icon: Icon, label }) => (
            <div
              className="flex items-center justify-center gap-2.5 bg-brand-base px-5 py-5 text-base text-brand-cream/70"
              key={label}
            >
              <Icon className="size-4 text-secondary" />
              {label}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
