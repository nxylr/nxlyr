import { CalendarCheck, CircleUserRound, FileText, Headphones } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

const capabilities = [
  {
    icon: FileText,
    title: "Project-aware answers",
    description: "Discusses the specific project’s pricing, floor plans, and amenities.",
  },
  {
    icon: CircleUserRound,
    title: "Intent qualification",
    description: "Distinguishes end-user needs from investor intent before a salesperson follows up.",
  },
  {
    icon: CalendarCheck,
    title: "Site-visit booking",
    description: "Captures a preferred time for the next site visit in the flow of the call.",
  },
  {
    icon: Headphones,
    title: "Human escalation",
    description: "Routes nuanced or out-of-scope conversations to the right person when appropriate.",
  },
];

export function Features() {
  return (
    <section id="features" className="scroll-mt-20 border-y border-secondary/70 bg-secondary/35 py-16 sm:py-20">
      <div className="mx-auto max-w-6xl px-6 lg:px-8">
        <p className="text-base font-medium text-primary">Features</p>
        <div className="mt-3 max-w-2xl">
          <h2 className="text-4xl font-semibold tracking-[-0.045em] text-foreground sm:text-5xl">
            The practical parts of the first sales conversation.
          </h2>
          <p className="mt-4 text-lg leading-8 text-muted-foreground">
            Each capability supports the handoff to a real salesperson; it does not replace their judgement.
          </p>
        </div>
        <div className="mt-10 grid gap-4 sm:grid-cols-2">
          {capabilities.map(({ icon: Icon, title, description }, index) => (
            <Card
              className={
                index === 0
                  ? "border border-secondary bg-secondary/60 py-0 shadow-none"
                  : "border border-border bg-background py-0 shadow-none"
              }
              key={title}
            >
              <CardContent className="flex gap-3 p-6">
                <span
                  className={`grid size-8 shrink-0 place-items-center rounded-md ${
                    index === 0 ? "bg-background/60 text-primary" : "bg-primary/10 text-primary"
                  }`}
                >
                  <Icon className="size-4" />
                </span>
                <div>
                  <h3 className="text-xl font-semibold text-foreground">{title}</h3>
                  <p className="mt-2 text-lg leading-8 text-muted-foreground">{description}</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
