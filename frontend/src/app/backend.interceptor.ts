import type { HttpInterceptorFn } from '@angular/common/http';
import { backendUrl } from './backend-url';

export const backendInterceptor: HttpInterceptorFn = (request, next) => {
  const url = backendUrl(request.url);
  return next(url === request.url ? request : request.clone({ url }));
};
