# Existing production demo-call logic

Source: `dashboard/index.html` as read in full before the Next.js scaffold was created.

This code is verified against real production calls. Preserve its E.164 normalization, absolute endpoint, request body, and every response-handling branch when implementing the replacement UI. `index.html` remains unchanged in this setup task.

```js
const form = document.getElementById('demo-form');
const phoneInput = document.getElementById('phone');
const submitButton = document.getElementById('submit-button');
const message = document.getElementById('form-message');
const demoCallUrl = 'https://api.infrasmith.dev/demo/call';

function normalizeIndianNumber(value) {
  const digits = value.replace(/\D/g, '');
  let mobile = digits;

  if (digits.length === 12 && digits.startsWith('91')) mobile = digits.slice(2);
  if (digits.length === 11 && digits.startsWith('0')) mobile = digits.slice(1);

  return /^[6-9]\d{9}$/.test(mobile) ? `+91${mobile}` : null;
}

function showMessage(text, type) {
  message.textContent = text;
  message.className = `message ${type}`;
  message.hidden = false;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  message.hidden = true;

  const phone = normalizeIndianNumber(phoneInput.value);
  if (!phone) {
    showMessage('Enter a valid 10-digit Indian mobile number.', 'error');
    phoneInput.focus();
    return;
  }

  phoneInput.value = phone;
  submitButton.disabled = true;
  submitButton.textContent = 'Requesting call…';

  try {
    const response = await fetch(demoCallUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({ phone_number: phone })
    });

    const payload = await response.json().catch(() => ({}));

    if (response.status === 200 && payload.status === 'success' && payload.type === 'call_triggered') {
      showMessage("Your demo call is on its way. Please answer within 60 seconds.", 'success');
      form.reset();
    } else if (response.status === 429 && payload.type === 'rate_limited' && payload.error === 'rate_limit_exceeded') {
      showMessage(payload.detail || 'Demo-call capacity has been reached. Please try again tomorrow.', 'error');
    } else if (response.status === 400 && payload.type === 'invalid_phone_number' && payload.error === 'invalid_phone_number') {
      showMessage(payload.detail || 'Enter a valid phone number in international format.', 'error');
      phoneInput.focus();
    } else if ((response.status === 500 || response.status === 502) && payload.status === 'error') {
      showMessage(payload.detail || 'We could not start your demo call. Please try again later.', 'error');
    } else {
      showMessage('We could not request your demo call right now. Please try again shortly.', 'error');
    }
  } catch (error) {
    showMessage('We could not request your demo call right now. Please try again shortly.', 'error');
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = 'Call me now';
  }
});
```
