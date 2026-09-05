export type DemoCallMessage = {
  text: string;
  type: "success" | "error";
  resetForm?: boolean;
  focusPhoneInput?: boolean;
};

type DemoCallPayload = {
  detail?: string;
  error?: string;
  status?: string;
  type?: string;
};

export const demoCallUrl = "https://api.infrasmith.dev/demo/call";

export function normalizeIndianNumber(value: string) {
  const digits = value.replace(/\D/g, "");
  let mobile = digits;

  if (digits.length === 12 && digits.startsWith("91")) mobile = digits.slice(2);
  if (digits.length === 11 && digits.startsWith("0")) mobile = digits.slice(1);

  return /^[6-9]\d{9}$/.test(mobile) ? `+91${mobile}` : null;
}

export async function requestDemoCall(phone: string): Promise<DemoCallMessage> {
  try {
    const response = await fetch(demoCallUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ phone_number: phone }),
    });

    const payload: DemoCallPayload = await response.json().catch(() => ({}));

    if (
      response.status === 200 &&
      payload.status === "success" &&
      payload.type === "call_triggered"
    ) {
      return {
        text: "Your demo call is on its way. Please answer within 60 seconds.",
        type: "success",
        resetForm: true,
      };
    } else if (
      response.status === 429 &&
      payload.type === "rate_limited" &&
      payload.error === "rate_limit_exceeded"
    ) {
      return {
        text:
          payload.detail ||
          "Demo-call capacity has been reached. Please try again tomorrow.",
        type: "error",
      };
    } else if (
      response.status === 400 &&
      payload.type === "invalid_phone_number" &&
      payload.error === "invalid_phone_number"
    ) {
      return {
        text:
          payload.detail ||
          "Enter a valid phone number in international format.",
        type: "error",
        focusPhoneInput: true,
      };
    } else if (
      (response.status === 500 || response.status === 502) &&
      payload.status === "error"
    ) {
      return {
        text:
          payload.detail ||
          "We could not start your demo call. Please try again later.",
        type: "error",
      };
    } else {
      return {
        text: "We could not request your demo call right now. Please try again shortly.",
        type: "error",
      };
    }
  } catch {
    return {
      text: "We could not request your demo call right now. Please try again shortly.",
      type: "error",
    };
  }
}
