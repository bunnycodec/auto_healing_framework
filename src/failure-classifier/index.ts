import {
  TraceData,
  TraceAction,
  FailureClassification,
  FailureCategory,
  DomSnapshot,
  NetworkEntry,
} from '../types';
import { findClosestSnapshot } from '../trace-parser';

/**
 * Analyzes trace data to classify the root cause of a test failure.
 */
export class FailureClassifier {
  /**
   * Classify the failure from parsed trace data.
   */
  classify(traceData: TraceData): FailureClassification {
    const failedAction = this.findFailedAction(traceData.actions);

    if (!failedAction) {
      return {
        category: 'unknown',
        confidence: 0.3,
        reason: 'No failed action found in trace data',
      };
    }

    // Check for locator failures first (most common healing target)
    const locatorResult = this.checkLocatorFailure(failedAction, traceData);
    if (locatorResult) return locatorResult;

    // Check for network failures
    const networkResult = this.checkNetworkFailure(failedAction, traceData);
    if (networkResult) return networkResult;

    // Check for timeout
    const timeoutResult = this.checkTimeout(failedAction, traceData);
    if (timeoutResult) return timeoutResult;

    // Check for assertion failures
    const assertionResult = this.checkAssertionFailure(failedAction);
    if (assertionResult) return assertionResult;

    // Check for environment issues
    const envResult = this.checkEnvironmentFailure(failedAction, traceData);
    if (envResult) return envResult;

    // Fallback
    return {
      category: 'unknown',
      confidence: 0.2,
      reason: `Unclassified failure: ${failedAction.error || 'Unknown error'}`,
      failedAction,
      relevantSnapshot: findClosestSnapshot(traceData.snapshots, failedAction.timestamp),
    };
  }

  private findFailedAction(actions: TraceAction[]): TraceAction | undefined {
    // Find the first failed action (typically the root cause)
    return actions.find(a => !a.success && a.error);
  }

  private checkLocatorFailure(
    action: TraceAction,
    traceData: TraceData
  ): FailureClassification | null {
    const error = action.error?.toLowerCase() || '';

    const locatorPatterns = [
      'waiting for selector',
      'waiting for locator',
      'no element matches selector',
      'element not found',
      'locator resolved to',
      'strict mode violation',
      'element is not visible',
      'element is not enabled',
      'element is not stable',
      'element is outside of the viewport',
      'target closed',
      'frame was detached',
      'element is detached',
      'selector resolved to hidden',
      'error: locator',
      'timeouterror: locator',
      'waiting for',
      'element does not have',
    ];

    const isLocatorFailure = locatorPatterns.some(p => error.includes(p));

    // Also check if the action had a selector and the error is a timeout
    const hasSelectorTimeout =
      action.selector &&
      (error.includes('timeout') || error.includes('timed out')) &&
      !error.includes('navigation');

    if (isLocatorFailure || hasSelectorTimeout) {
      const snapshot = findClosestSnapshot(traceData.snapshots, action.timestamp);
      return {
        category: 'locator',
        confidence: isLocatorFailure ? 0.95 : 0.75,
        reason: `Locator failure: ${action.error}. Selector "${action.selector}" could not find a matching element.`,
        failedAction: action,
        relevantSnapshot: snapshot,
      };
    }

    return null;
  }

  private checkNetworkFailure(
    action: TraceAction,
    traceData: TraceData
  ): FailureClassification | null {
    const error = action.error?.toLowerCase() || '';
    const networkPatterns = [
      'net::err',
      'network error',
      'fetch failed',
      'econnrefused',
      'enotfound',
      'socket hang up',
      'dns lookup failed',
    ];

    if (networkPatterns.some(p => error.includes(p))) {
      const failedRequests = traceData.network.filter(n => n.failed);
      return {
        category: 'network',
        confidence: 0.9,
        reason: `Network failure: ${action.error}`,
        failedAction: action,
        relevantNetwork: failedRequests,
      };
    }

    // Check for API errors around the time of failure
    const nearbyFailedRequests = traceData.network.filter(
      n => n.failed && Math.abs(n.timestamp - action.timestamp) < 5000
    );

    if (nearbyFailedRequests.length > 0 && error.includes('timeout')) {
      return {
        category: 'network',
        confidence: 0.7,
        reason: `Possible network-related timeout. ${nearbyFailedRequests.length} failed request(s) near the failure time.`,
        failedAction: action,
        relevantNetwork: nearbyFailedRequests,
      };
    }

    return null;
  }

  private checkTimeout(
    action: TraceAction,
    traceData: TraceData
  ): FailureClassification | null {
    const error = action.error?.toLowerCase() || '';

    if (
      (error.includes('timeout') || error.includes('timed out')) &&
      !action.selector // Not a locator timeout
    ) {
      return {
        category: 'timeout',
        confidence: 0.8,
        reason: `Timeout: ${action.error}`,
        failedAction: action,
        relevantSnapshot: findClosestSnapshot(traceData.snapshots, action.timestamp),
      };
    }

    return null;
  }

  private checkAssertionFailure(
    action: TraceAction
  ): FailureClassification | null {
    const error = action.error?.toLowerCase() || '';
    const type = action.type?.toLowerCase() || '';

    const assertionPatterns = [
      'expect(',
      'assert',
      'tobehidden',
      'tobevisible',
      'tohavetext',
      'tohavevalue',
      'tohavecount',
      'tocontaintext',
      'tohaveattribute',
      'tohavetitle',
      'tohaveurl',
      'received:',
      'expected:',
    ];

    if (
      assertionPatterns.some(p => error.includes(p)) ||
      type.includes('expect')
    ) {
      return {
        category: 'assertion',
        confidence: 0.85,
        reason: `Assertion failure: ${action.error}`,
        failedAction: action,
      };
    }

    return null;
  }

  private checkEnvironmentFailure(
    action: TraceAction,
    traceData: TraceData
  ): FailureClassification | null {
    const error = action.error?.toLowerCase() || '';

    const envPatterns = [
      'browser has been closed',
      'context has been closed',
      'page has been closed',
      'crashed',
      'process exited',
      'target page, context or browser has been closed',
      'protocol error',
      'session closed',
    ];

    if (envPatterns.some(p => error.includes(p))) {
      return {
        category: 'environment',
        confidence: 0.85,
        reason: `Environment failure: ${action.error}`,
        failedAction: action,
      };
    }

    return null;
  }
}
