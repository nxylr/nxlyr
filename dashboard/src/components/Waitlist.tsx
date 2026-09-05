"use client";

import { type FormEvent, useState } from "react";
import { CheckCircle2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type WaitlistValues = {
  company: string;
  email: string;
  name: string;
};

type FieldErrors = Partial<Record<keyof WaitlistValues, string>>;
type SubmissionStatus = "idle" | "submitting" | "success" | "error";

async function submitWaitlistPlaceholder(values: WaitlistValues) {
  // TODO: no backend endpoint exists yet for waitlist capture — this
  // currently does not persist anywhere. Needs a real decision on
  // where this data goes (new API endpoint + Supabase table, or another
  // mechanism) before this goes live.
  void values;
  await new Promise((resolve) => window.setTimeout(resolve, 700));
}

function validateWaitlist(values: WaitlistValues): FieldErrors {
  const errors: FieldErrors = {};

  if (values.name.trim().length < 2) {
    errors.name = "Enter your name.";
  }

  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email.trim())) {
    errors.email = "Enter a valid email address.";
  }

  return errors;
}

export function Waitlist() {
  const [values, setValues] = useState<WaitlistValues>({
    company: "",
    email: "",
    name: "",
  });
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [status, setStatus] = useState<SubmissionStatus>("idle");

  function updateField(field: keyof WaitlistValues, value: string) {
    setValues((current) => ({ ...current, [field]: value }));
    setFieldErrors((current) => ({ ...current, [field]: undefined }));
    if (status === "error") setStatus("idle");
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const errors = validateWaitlist(values);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      setStatus("error");
      return;
    }

    setStatus("submitting");

    try {
      await submitWaitlistPlaceholder(values);
      setStatus("success");
    } catch {
      setStatus("error");
    }
  }

  return (
    <section id="waitlist" className="scroll-mt-20 border-t border-muted/70 bg-background py-16 sm:py-20">
      <div className="mx-auto grid max-w-6xl gap-10 px-6 lg:grid-cols-[0.85fr_1.15fr] lg:px-8">
        <div>
          <p className="text-base font-medium text-primary">Get in Touch</p>
          <h2 className="mt-3 text-4xl font-semibold tracking-[-0.045em] text-foreground sm:text-5xl">
            Let’s talk about your sales team.
          </h2>
          <p className="mt-4 max-w-md text-lg leading-8 text-muted-foreground">
            Tell us about your team and the first conversations you want to improve.
          </p>
          <p className="mt-4 text-sm leading-6 text-muted-foreground">
            Review-mode form: submissions are simulated and are not stored anywhere yet.
          </p>
        </div>

        <div className="rounded-xl border border-muted bg-muted/45 p-6">
          {status === "success" ? (
            <div role="status" aria-live="polite" className="flex min-h-64 flex-col justify-center">
              <CheckCircle2 className="size-8 text-secondary" />
              <h3 className="mt-5 text-2xl font-semibold text-foreground">
                Form state confirmed.
              </h3>
              <p className="mt-2 max-w-md text-base leading-7 text-muted-foreground">
                This is the intended success UI. Your details were not stored because contact-form persistence has not been connected yet.
              </p>
              <Button
                type="button"
                variant="outline"
                onClick={() => setStatus("idle")}
                className="mt-6 w-fit"
              >
                Test the form again
              </Button>
            </div>
          ) : (
            <form noValidate onSubmit={handleSubmit}>
              <div>
                <label className="mb-2 block text-base font-medium text-foreground" htmlFor="waitlist-name">
                  Name
                </label>
                <Input
                  id="waitlist-name"
                  name="name"
                  autoComplete="name"
                  required
                  aria-invalid={Boolean(fieldErrors.name)}
                  aria-describedby={fieldErrors.name ? "waitlist-name-error" : undefined}
                  value={values.name}
                  onChange={(event) => updateField("name", event.target.value)}
                  className="h-11 bg-card"
                />
                {fieldErrors.name ? (
                  <p id="waitlist-name-error" className="mt-1.5 text-sm text-destructive">
                    {fieldErrors.name}
                  </p>
                ) : null}
              </div>

              <div className="mt-5">
                <label className="mb-2 block text-base font-medium text-foreground" htmlFor="waitlist-email">
                  Email
                </label>
                <Input
                  id="waitlist-email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  required
                  aria-invalid={Boolean(fieldErrors.email)}
                  aria-describedby={fieldErrors.email ? "waitlist-email-error" : undefined}
                  value={values.email}
                  onChange={(event) => updateField("email", event.target.value)}
                  className="h-11 bg-card"
                />
                {fieldErrors.email ? (
                  <p id="waitlist-email-error" className="mt-1.5 text-sm text-destructive">
                    {fieldErrors.email}
                  </p>
                ) : null}
              </div>

              <div className="mt-5">
                <label className="mb-2 block text-base font-medium text-foreground" htmlFor="waitlist-company">
                  Company or developer name <span className="text-muted-foreground">(optional)</span>
                </label>
                <Input
                  id="waitlist-company"
                  name="company"
                  autoComplete="organization"
                  value={values.company}
                  onChange={(event) => updateField("company", event.target.value)}
                  className="h-11 bg-card"
                />
              </div>

              {status === "error" && Object.keys(fieldErrors).length === 0 ? (
                <p className="mt-5 text-base text-destructive" role="alert">
                  The simulated submission could not complete. Please try again.
                </p>
              ) : null}

              <Button type="submit" disabled={status === "submitting"} className="mt-6 h-12 px-6 text-base">
                {status === "submitting" ? "Checking form…" : "Start a conversation"}
              </Button>
            </form>
          )}
        </div>
      </div>
    </section>
  );
}
