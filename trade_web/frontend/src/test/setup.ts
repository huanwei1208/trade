import "@testing-library/jest-dom/vitest";

// Vitest setup: jest-dom matchers (toHaveTextContent, toBeTruthy helpers) plus a
// no-op matchMedia so components relying on it do not crash under jsdom.
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  });
}
