import { Features } from "@/components/Capabilities";
import { Footer } from "@/components/Footer";
import { Header } from "@/components/Header";
import { Hero } from "@/components/Hero";
import { HowItWorks } from "@/components/HowItWorks";
import { Mission } from "@/components/Mission";
import { WhatWeDo } from "@/components/WhatWeDo";
import { Waitlist } from "@/components/Waitlist";
import { WhyThisMatters } from "@/components/WhyThisMatters";

export default function Home() {
  return (
    <>
      <Header />
      <main>
        <Hero />
        <Features />
        <WhatWeDo />
        <WhyThisMatters />
        <HowItWorks />
        <Mission />
        <Waitlist />
      </main>
      <Footer />
    </>
  );
}
