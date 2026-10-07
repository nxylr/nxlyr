import { ArrowUpRight, MessageSquareText } from "lucide-react";

export function WhatWeDo() {
  return (
    <section id="what-we-do" className="scroll-mt-20 border-b border-muted bg-background py-16 sm:py-20">
      <div className="mx-auto grid max-w-6xl gap-10 px-6 lg:grid-cols-[0.8fr_1.2fr] lg:gap-20 lg:px-8">
        <div>
          <p className="text-base font-medium text-primary">What we do</p>
          <h2 className="mt-3 text-4xl font-semibold tracking-[-0.045em] text-foreground sm:text-5xl">
            Turn fresh enquiries into informed follow-ups.
          </h2>
        </div>
        <div className="grid gap-px overflow-hidden rounded-xl border border-muted bg-muted sm:grid-cols-2">
          <div className="bg-muted p-7">
            <span className="grid size-8 place-items-center rounded-md bg-background/60 text-primary">
              <MessageSquareText className="size-4" />
            </span>
            <h3 className="mt-4 text-xl font-semibold text-foreground">A useful first conversation</h3>
            <p className="mt-2 text-lg leading-8 text-muted-foreground">
              In the demo, an AI voice agent calls your phone and talks about one fictional project.
            </p>
          </div>
          <div className="bg-background/70 p-7">
            <span className="grid size-8 place-items-center rounded-md bg-muted/60 text-primary">
              <ArrowUpRight className="size-4" />
            </span>
            <h3 className="mt-4 text-xl font-semibold text-foreground">Where we are heading</h3>
            <p className="mt-2 text-lg leading-8 text-muted-foreground">
              Handoff to your sales team is planned but not built yet.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
