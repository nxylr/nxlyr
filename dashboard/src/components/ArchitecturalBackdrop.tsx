type ArchitecturalBackdropProps = {
  variant?: "hero" | "section";
};

export function ArchitecturalBackdrop({ variant = "hero" }: ArchitecturalBackdropProps) {
  const isHero = variant === "hero";

  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
      <div
        className={`absolute inset-0 ${isHero ? "opacity-75" : "opacity-40"}`}
        style={{
          backgroundImage: [
            "linear-gradient(to right, color-mix(in oklch, var(--secondary) 12%, transparent) 1px, transparent 1px)",
            "linear-gradient(to bottom, color-mix(in oklch, var(--secondary) 12%, transparent) 1px, transparent 1px)",
            "linear-gradient(to right, color-mix(in oklch, var(--primary) 8%, transparent) 1px, transparent 1px)",
            "linear-gradient(to bottom, color-mix(in oklch, var(--primary) 8%, transparent) 1px, transparent 1px)",
          ].join(", "),
          backgroundPosition: "center",
          backgroundSize: "4rem 4rem, 4rem 4rem, 1rem 1rem, 1rem 1rem",
          maskImage: "linear-gradient(to bottom, transparent, black 18%, black 82%, transparent)",
        }}
      />

      <svg
        className={`absolute inset-x-0 bottom-0 w-full text-primary ${
          isHero ? "h-[52%] opacity-[0.22]" : "h-[34%] opacity-[0.1]"
        }`}
        viewBox="0 0 1440 420"
        fill="none"
        preserveAspectRatio="none"
      >
        <path
          d="M0 365H95V248H148V365H214V192H282V365H350V272H414V365H478V142H552V365H621V230H696V365H762V176H838V365H908V260H972V365H1040V116H1124V365H1195V220H1268V365H1332V286H1386V365H1440"
          stroke="currentColor"
          strokeWidth="1.5"
        />
        <path d="M478 142L515 102L552 142M1040 116L1082 70L1124 116" stroke="currentColor" strokeWidth="1.5" />
        <path d="M0 365H1440" stroke="currentColor" strokeWidth="1.5" />
        <path d="M232 224H264M496 188H534M787 224H818M1061 170H1102M1216 258H1248" stroke="currentColor" strokeWidth="1" />
      </svg>

      <svg
        className={`absolute text-secondary ${
          isHero
            ? "right-0 top-[4%] h-[50%] w-[50%] opacity-[0.18]"
            : "right-[3%] top-[8%] h-[38%] w-[42%] opacity-[0.1]"
        }`}
        viewBox="0 0 600 360"
        fill="none"
      >
        <path d="M80 310L300 62L520 310Z" stroke="currentColor" strokeWidth="1.25" />
        <path d="M136 310L300 126L464 310M300 62V310M190 250H410M238 194H362" stroke="currentColor" strokeWidth="1" />
        <circle cx="300" cy="194" r="128" stroke="currentColor" strokeDasharray="6 10" />
      </svg>
    </div>
  );
}
