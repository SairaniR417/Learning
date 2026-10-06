import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, inject } from '@angular/core';
import { Subscription, timer } from 'rxjs';
import { EmaScannerComponent } from './scanner/ema-scanner.component';
import { MarketApiService } from './market-api.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, EmaScannerComponent],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css'
})
export class AppComponent implements OnInit, OnDestroy {
  private readonly api = inject(MarketApiService);
  private statusSubscription?: Subscription;
  private clockSubscription?: Subscription;
  connected = false;
  clock = '';

  ngOnInit(): void {
    this.statusSubscription = timer(0, 15000).subscribe(() => {
      this.api.status().subscribe({ next: (status) => this.connected = status.connected });
    });
    this.clockSubscription = timer(0, 1000).subscribe(() => {
      this.clock = new Intl.DateTimeFormat('en-IN', {
        timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
      }).format(new Date()) + ' IST';
    });
  }

  ngOnDestroy(): void {
    this.statusSubscription?.unsubscribe();
    this.clockSubscription?.unsubscribe();
  }

  disconnect(): void {
    this.api.logout().subscribe({
      next: () => this.connected = false,
      error: () => this.connected = false
    });
  }
}
