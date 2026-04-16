export {};

declare global {
  interface NexgenBridge {
    readonly apiBaseUrl: string;
    readonly wsBaseUrl: string;
    readonly launchToken: string;
    readonly isPackaged: boolean;
  }

  interface Window {
    readonly nexgen: NexgenBridge;
  }
}
