import * as fs from 'fs';
import * as path from 'path';
import JSZip from 'jszip';
import {
  TraceData,
  TraceAction,
  DomSnapshot,
  NetworkEntry,
  TraceMetadata,
} from '../types';

/**
 * Parses Playwright trace zip files and extracts structured trace data
 * including DOM snapshots, network traffic, and action logs.
 */
export class TraceParser {
  /**
   * Parse a Playwright trace zip file into structured TraceData.
   */
  async parse(tracePath: string): Promise<TraceData> {
    const absolutePath = path.resolve(tracePath);
    if (!fs.existsSync(absolutePath)) {
      throw new Error(`Trace file not found: ${absolutePath}`);
    }

    const zipBuffer = fs.readFileSync(absolutePath);
    const zip = await JSZip.loadAsync(zipBuffer);

    const actions = await this.extractActions(zip);
    const snapshots = await this.extractSnapshots(zip);
    const network = await this.extractNetwork(zip);
    const metadata = await this.extractMetadata(zip, actions);

    return { actions, snapshots, network, metadata };
  }

  /**
   * Parse multiple trace files from a directory.
   */
  async parseDirectory(dirPath: string): Promise<TraceData[]> {
    const absolutePath = path.resolve(dirPath);
    const files = fs.readdirSync(absolutePath)
      .filter(f => f.endsWith('.zip'))
      .map(f => path.join(absolutePath, f));

    return Promise.all(files.map(f => this.parse(f)));
  }

  private async extractActions(zip: JSZip): Promise<TraceAction[]> {
    const actions: TraceAction[] = [];

    // Playwright trace stores actions in trace.trace files (newline-delimited JSON)
    for (const [filename, file] of Object.entries(zip.files)) {
      if (filename.endsWith('.trace') || filename.endsWith('.jsonl')) {
        const content = await file.async('string');
        const lines = content.split('\n').filter(l => l.trim());

        for (const line of lines) {
          try {
            const event = JSON.parse(line);
            const action = this.parseTraceEvent(event);
            if (action) {
              actions.push(action);
            }
          } catch {
            // Skip malformed JSON lines
          }
        }
      }
    }

    return actions.sort((a, b) => a.timestamp - b.timestamp);
  }

  private parseTraceEvent(event: Record<string, unknown>): TraceAction | null {
    const type = event.type as string | undefined;

    // Handle 'action' events from Playwright traces
    if (type === 'action' || type === 'event') {
      const params = (event.params as Record<string, unknown>) || {};
      const metadata = (event.metadata as Record<string, unknown>) || {};
      const error = (event.error as Record<string, string>) || {};

      return {
        type: (metadata.type as string) || (event.method as string) || type,
        selector: params.selector as string | undefined,
        url: params.url as string | undefined,
        value: params.value as string | undefined,
        timestamp: (event.startTime as number) || (event.timestamp as number) || 0,
        success: !event.error,
        error: error.message || (event.error as string | undefined),
        stack: (metadata.stack as string | undefined) ||
               (event.stack as string | undefined),
        pageUrl: params.url as string | undefined,
      };
    }

    // Handle 'before' and 'after' action events
    if (type === 'before' || type === 'after' || type === 'input') {
      const callId = event.callId as string;
      const params = (event.params as Record<string, unknown>) || {};
      const stack = event.stack as string | undefined;

      return {
        type: (event.apiName as string) || (event.method as string) || type,
        selector: params.selector as string | undefined,
        url: params.url as string | undefined,
        value: params.value as string | undefined,
        timestamp: (event.startTime as number) || (event.wallTime as number) || 0,
        success: type !== 'after' || !event.error,
        error: event.error ? JSON.stringify(event.error) : undefined,
        stack: stack || (event.point as Record<string, unknown>)
          ? this.formatStackFromPoint(event)
          : undefined,
        pageUrl: params.url as string | undefined,
      };
    }

    return null;
  }

  private formatStackFromPoint(event: Record<string, unknown>): string | undefined {
    const stack = event.stack as Array<Record<string, unknown>> | undefined;
    if (!stack || !Array.isArray(stack)) return undefined;

    return stack
      .map(frame => {
        const file = frame.file as string;
        const line = frame.line as number;
        const column = frame.column as number;
        const func = frame.function as string || '<anonymous>';
        return `    at ${func} (${file}:${line}:${column})`;
      })
      .join('\n');
  }

  private async extractSnapshots(zip: JSZip): Promise<DomSnapshot[]> {
    const snapshots: DomSnapshot[] = [];

    for (const [filename, file] of Object.entries(zip.files)) {
      // Playwright stores snapshots as HTML files or in resources
      if (filename.endsWith('.html') || filename.includes('snapshot')) {
        try {
          const html = await file.async('string');
          snapshots.push({
            html,
            url: filename,
            timestamp: Date.now(),
          });
        } catch {
          // Skip files that can't be read as text
        }
      }

      // Also parse snapshot entries from trace events
      if (filename.endsWith('.trace') || filename.endsWith('.jsonl')) {
        const content = await file.async('string');
        const lines = content.split('\n').filter(l => l.trim());

        for (const line of lines) {
          try {
            const event = JSON.parse(line);
            if (event.type === 'resource-snapshot' || event.type === 'snapshot') {
              const snapshot = event.snapshot as Record<string, unknown>;
              if (snapshot && typeof snapshot === 'object') {
                snapshots.push({
                  html: (snapshot.html as string) || JSON.stringify(snapshot),
                  url: (snapshot.url as string) || (event.pageUrl as string) || '',
                  timestamp: (event.timestamp as number) || (event.wallTime as number) || 0,
                });
              }
            }
          } catch {
            // Skip malformed lines
          }
        }
      }
    }

    return snapshots.sort((a, b) => a.timestamp - b.timestamp);
  }

  private async extractNetwork(zip: JSZip): Promise<NetworkEntry[]> {
    const entries: NetworkEntry[] = [];

    for (const [filename, file] of Object.entries(zip.files)) {
      if (filename.endsWith('.trace') || filename.endsWith('.jsonl')) {
        const content = await file.async('string');
        const lines = content.split('\n').filter(l => l.trim());

        for (const line of lines) {
          try {
            const event = JSON.parse(line);
            if (event.type === 'resource-snapshot' &&
                event.resourceType === 'fetch' || event.resourceType === 'xhr') {
              const response = (event.response as Record<string, unknown>) || {};
              entries.push({
                url: (event.url as string) || '',
                method: (event.method as string) || 'GET',
                status: (response.status as number) || 0,
                timestamp: (event.timestamp as number) || 0,
                duration: (event.duration as number) || 0,
                resourceType: (event.resourceType as string) || 'other',
                failed: (response.status as number) >= 400 || !!(event.error),
                failureText: event.error ? String(event.error) : undefined,
              });
            }
          } catch {
            // Skip malformed lines
          }
        }
      }
    }

    return entries.sort((a, b) => a.timestamp - b.timestamp);
  }

  private async extractMetadata(
    zip: JSZip,
    actions: TraceAction[]
  ): Promise<TraceMetadata> {
    let metadata: TraceMetadata = {
      testName: 'unknown',
      testFile: 'unknown',
      browser: 'chromium',
      startTime: 0,
      endTime: 0,
      status: 'failed',
    };

    // Look for test-info or context entries in trace
    for (const [filename, file] of Object.entries(zip.files)) {
      if (filename.endsWith('.trace') || filename.endsWith('.jsonl')) {
        const content = await file.async('string');
        const lines = content.split('\n').filter(l => l.trim());

        for (const line of lines) {
          try {
            const event = JSON.parse(line);
            if (event.type === 'context-options' || event.type === 'test-info') {
              const testId = event.testId as Record<string, unknown> | undefined;
              if (testId) {
                metadata.testName = (testId.title as string) || metadata.testName;
                metadata.testFile = (testId.file as string) || metadata.testFile;
              }
              if (event.title) {
                metadata.testName = event.title as string;
              }
              if (event.file) {
                metadata.testFile = event.file as string;
              }
              if (event.browserName) {
                metadata.browser = event.browserName as string;
              }
            }
          } catch {
            // Skip
          }
        }
      }
    }

    // Derive timing from actions
    if (actions.length > 0) {
      metadata.startTime = actions[0].timestamp;
      metadata.endTime = actions[actions.length - 1].timestamp;
    }

    // Check if any action failed
    const failedAction = actions.find(a => !a.success);
    if (failedAction) {
      metadata.status = 'failed';
      metadata.error = failedAction.error;

      // Try to extract test file from stack trace
      if (failedAction.stack && metadata.testFile === 'unknown') {
        const stackMatch = failedAction.stack.match(/at\s+.*\((.+?\.(spec|test)\.(ts|js|mjs)):(\d+):\d+\)/);
        if (stackMatch) {
          metadata.testFile = stackMatch[1];
        }
      }
    }

    return metadata;
  }
}

/**
 * Finds the DOM snapshot closest to a given timestamp.
 */
export function findClosestSnapshot(
  snapshots: DomSnapshot[],
  timestamp: number
): DomSnapshot | undefined {
  if (snapshots.length === 0) return undefined;

  let closest = snapshots[0];
  let minDiff = Math.abs(closest.timestamp - timestamp);

  for (const snapshot of snapshots) {
    const diff = Math.abs(snapshot.timestamp - timestamp);
    if (diff < minDiff) {
      closest = snapshot;
      minDiff = diff;
    }
  }

  return closest;
}
