export type ContactSubmissionMessage = {
  text: string;
  type: "success" | "error";
};

type ContactPayload = {
  detail?: string;
  error?: string;
  status?: string;
  type?: string;
};

export type ContactSubmission = {
  company: string;
  email: string;
  name: string;
};

export const contactUrl = "https://api.infrasmith.dev/contact";

export async function submitContact(
  contact: ContactSubmission,
): Promise<ContactSubmissionMessage> {
  try {
    const response = await fetch(contactUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(contact),
    });
    const payload: ContactPayload = await response.json().catch(() => ({}));

    if (
      response.status === 200 &&
      payload.status === "success" &&
      payload.type === "contact_stored"
    ) {
      return {
        type: "success",
        text: "Thanks — your details are with us. We’ll be in touch.",
      };
    }

    if (
      response.status === 429 &&
      payload.type === "rate_limited" &&
      payload.error === "rate_limit_exceeded"
    ) {
      return {
        type: "error",
        text:
          payload.detail ||
          "We’ve received several requests from this email. Please try again tomorrow.",
      };
    }

    if (
      response.status === 400 &&
      payload.type === "invalid_contact_submission" &&
      payload.error === "invalid_contact_submission"
    ) {
      return {
        type: "error",
        text: payload.detail || "Enter your name and a valid email address.",
      };
    }

    if (response.status === 500 && payload.status === "error") {
      return {
        type: "error",
        text:
          payload.detail ||
          "We could not save your details right now. Please try again later.",
      };
    }

    return {
      type: "error",
      text: "We could not save your details right now. Please try again later.",
    };
  } catch {
    return {
      type: "error",
      text: "We could not save your details right now. Please try again later.",
    };
  }
}
