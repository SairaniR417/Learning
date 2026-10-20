import { CommonModule } from '@angular/common';
import { Component, EventEmitter, OnInit, Output, DestroyRef, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MarketApiService, SelectedStock } from '../market-api.service';

@Component({
  selector: 'app-fno-stocks',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './fno-stocks.component.html',
  styleUrl: './fno-stocks.component.css',
})
export class FnoStocksComponent implements OnInit {
  private readonly api = inject(MarketApiService);
  private readonly destroyRef = inject(DestroyRef);
  @Output() stockSelected = new EventEmitter<SelectedStock>();
  stocks: SelectedStock[] = [];
  query = '';
  loading = true;
  error = '';

  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading = true;
    this.error = '';
    this.api.fnoStocks().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: response => { this.stocks = response.stocks; this.loading = false; },
      error: () => {
        this.error = 'Could not load the saved F&O stock list. Please try again.';
        this.loading = false;
      },
    });
  }

  get filteredStocks(): SelectedStock[] {
    const query = this.query.trim().toLowerCase();
    return this.stocks.filter(stock =>
      stock.symbol.toLowerCase().includes(query) || stock.name.toLowerCase().includes(query));
  }
}
