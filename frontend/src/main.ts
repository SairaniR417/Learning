import { bootstrapApplication } from '@angular/platform-browser';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { AppComponent } from './app/app.component';
import { backendInterceptor } from './app/backend.interceptor';

bootstrapApplication(AppComponent, { providers: [provideHttpClient(withInterceptors([backendInterceptor]))] }).catch((error: unknown) => console.error(error));
