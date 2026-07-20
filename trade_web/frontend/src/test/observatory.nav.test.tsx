import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AppShell } from "../components/AppShell";
import { I18nProvider } from "../lib/i18n";

afterEach(() => cleanup());

/**
 * RA.1 (docs/27 Phase A, F14): the Observatory nav entry is gated on the App-level
 * `observatoryAuthorized` boolean, which is true ONLY for a fresh, successful
 * capability response with show_nav (see App.tsx). These AppShell-injection tests
 * assert the shell honors that boolean; they are NOT sufficient on their own — the
 * freshness/fail-closed behavior is covered by the App-level tests in
 * observatory.app.test.tsx.
 */
function renderShell(authorized: boolean | undefined) {
  return render(
    <I18nProvider locale="en-US">
      <AppShell
        activePage="today"
        pageTitle="Today"
        pageSubtitle=""
        locale="en-US"
        asOf="2026-07-20"
        observatoryAuthorized={authorized}
        onNavigate={() => {}}
        onLocaleChange={() => {}}
        onRefresh={() => {}}
      >
        <div>content</div>
      </AppShell>
    </I18nProvider>,
  );
}

describe("Observatory nav gating (AppShell)", () => {
  it("shows the Observatory nav entry only when authorized is true", () => {
    renderShell(true);
    expect(screen.getByTestId("nav-observatory")).toBeTruthy();
  });

  it.each([false, undefined])("hides the Observatory nav when authorized is %s", (authorized) => {
    renderShell(authorized);
    expect(screen.queryByTestId("nav-observatory")).toBeNull();
    // Other nav entries still render.
    expect(screen.getByTestId("nav-today")).toBeTruthy();
  });
});
