import "@testing-library/jest-dom/vitest";

// jsdom has no EventSource; stub it so components that stream live job progress can mount in tests.
class FakeEventSource {
  addEventListener(): void {}
  close(): void {}
}
globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;

// jsdom lacks blob URL helpers used by file downloads.
URL.createObjectURL = () => "blob:test";
URL.revokeObjectURL = () => {};
