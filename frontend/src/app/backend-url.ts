import { environment } from '../environments/environment';

/** Resolve only application backend paths; leave external URLs and assets alone. */
export function resolveBackendUrl(url: string, baseUrl: string): string {
  if (!baseUrl || !/^\/?(?:api|auth|oauth|kite)(?:\/|[?#]|$)/.test(url)) return url;
  return baseUrl.replace(/\/+$/, '') + '/' + url.replace(/^\//, '');
}

// Also used for browser navigation, which does not pass through HttpClient.
export function backendUrl(path: string): string {
  return resolveBackendUrl(path, environment.apiBaseUrl);
}
