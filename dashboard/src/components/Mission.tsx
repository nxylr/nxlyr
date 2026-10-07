import { Focus, MapPinned, PhoneForwarded, ShieldCheck } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

// Placeholder mission copy pending the founder's real input; not finalized.
const missionCards = [
  {
    icon: Focus,
    title: "Free your sales team to close, not dial",
    description:
      "We are building NXLYR to take on the first-call workload so human sales staff can focus on buyers who are ready to talk.",
  },
  {
    icon: PhoneForwarded,
    title: "Our goal: a prompt first conversation for every lead",
    description:
      "We want every enquiry to get a useful first response while interest is fresh. Today you can try this through the public demo call.",
  },
  {
    icon: ShieldCheck,
    title: "Who handles your data",
    description:
      "To deliver this demo we use third-party providers: Exotel (calls), Deepgram (speech-to-text), OpenAI (language), ElevenLabs (voice), Supabase (storage), Vercel (hosting) and Telegram (internal notifications).",
  },
  {
    icon: MapPinned,
    title: "Focused on Indian real estate",
    description:
      "We are building for Indian real-estate developers, starting with a demo that calls Indian mobile numbers and talks about a property project.",
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
