import { Injectable, OnDestroy, inject } from '@angular/core';
import { EMPTY, Subscription, catchError, exhaustMap, timer } from 'rxjs';
import { AlertNotification, MarketApiService, NotificationInbox } from './market-api.service';

@Injectable({ providedIn: 'root' })
export class AlertNotificationsService implements OnDestroy {
  private api = inject(MarketApiService);
  inbox: NotificationInbox = { notifications: [], unread: 0, monitor: { running: false, lastCheck: null, error: '' } };
  error = '';
  toast: AlertNotification | null = null;
  private seen = new Set<number>();
  private subscription: Subscription;
  private toastTimer?: ReturnType<typeof setTimeout>;
  desktopStatus = typeof Notification === 'undefined' ? 'unsupported' : Notification.permission;
  constructor() {
    try { this.seen = new Set(JSON.parse(localStorage.getItem('traders-gita-notified-alerts') ?? '[]')); } catch {}
    this.subscription = timer(0, 15000).pipe(exhaustMap(() => this.api.notificationInbox().pipe(catchError(() => {
      this.error = 'Cannot reach alert monitoring. Check the API connection.'; return EMPTY;
    })))).subscribe(data => this.accept(data));
  }
  private accept(data: NotificationInbox): void {
    this.error = ''; this.inbox = data;
    const fresh = data.notifications.filter(n => !n.read && !this.seen.has(n.id));
    for (const item of fresh) {
      this.seen.add(item.id);
      if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        try { new Notification(`${item.symbol} price alert`, { body: item.message, tag: `price-alert-${item.id}` }); } catch {}
      }
    }
    if (fresh.length) {
      this.toast = fresh[0]; clearTimeout(this.toastTimer);
      this.toastTimer = setTimeout(() => this.toast = null, 12000);
      try { localStorage.setItem('traders-gita-notified-alerts', JSON.stringify([...this.seen].slice(-500))); } catch {}
    }
  }
  refresh(): void { this.api.notificationInbox().subscribe({ next: data => this.accept(data), error: () => this.error = 'Cannot reach alert monitoring. Check the API connection.' }); }
  markRead(): void { this.api.readNotifications().subscribe({ next: () => this.refresh(), error: () => this.error = 'Could not mark notifications as read.' }); }
  markOne(id: number): void { this.api.readNotification(id).subscribe({ next: () => this.refresh(), error: () => this.error = 'Could not mark notification as read.' }); }
  async enableDesktop(): Promise<void> {
    if (typeof Notification === 'undefined') return;
    try { this.desktopStatus = await Notification.requestPermission(); } catch { this.desktopStatus = 'denied'; }
  }
  ngOnDestroy(): void { this.subscription.unsubscribe(); clearTimeout(this.toastTimer); }
}
