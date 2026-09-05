import { Focus, MapPinned, PhoneForwarded, ShieldCheck } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

// Placeholder mission copy pending the founder's real input; not finalized.
const missionCards = [
  {
    icon: Focus,
    title: "Free your sales team to close, not dial",
    description:
      "NXLYR handles the first-call workload so human sales staff can focus on converting the buyers already standing on-site.",
  },
  {
    icon: PhoneForwarded,
    title: "Every lead gets an instant, consistent first conversation",
    description:
      "Every enquiry receives a useful first response while intent is fresh, instead of falling through the cracks waiting for a callback.",
  },
  {
    icon: ShieldCheck,
    title: "Data stays with you",
    description:
      "Lead data is handled under India’s DPDP Act and is not shared with brokers or other third parties.",
  },
  {
    icon: MapPinned,
    title: "Built for how Indian real estate actually sells",
    description:
      "This is not a generic voice-AI wrapper. The product is being tuned for the projects, buyer questions, site visits, and handoffs specific to this market.",
  },
];

export function Mission() {
  return (
    <section id="mission" className="scroll-mt-20 bg-muted/25 py-16 sm:py-20">
      <div className="mx-auto max-w-6xl px-6 lg:px-8">
        <p className="text-base font-medium text-primary">Our mission</p>
        <h2 className="mt-3 max-w-3xl text-4xl font-semibold tracking-[-0.045em] text-foreground sm:text-5xl">
          Give developers the best possible pre-sales team.
        </h2>

        <div className="mt-10 grid gap-4 sm:grid-cols-2">
          {missionCards.map(({ icon: Icon, title, description }, index) => (
            <Card
              className={
                index === 2
                  ? "border border-primary bg-primary py-0 shadow-lg shadow-primary/20"
                  : "border border-border bg-card py-0 shadow-none"
              }
              key={title}
            >
              <CardContent className="p-6">
                <span className={`grid size-8 place-items-center rounded-md ${
                  index === 2
                    ? "bg-brand-cream/15 text-primary-foreground"
                    : "bg-secondary/12 text-secondary"
                }`}>
                  <Icon className="size-4" />
                </span>
                <h3 className={`mt-4 text-xl font-semibold ${
                  index === 2 ? "text-primary-foreground" : "text-foreground"
                }`}>{title}</h3>
                <p className={`mt-2 text-lg leading-8 ${
                  index === 2 ? "text-primary-foreground/80" : "text-muted-foreground"
                }`}>
                  {description}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
