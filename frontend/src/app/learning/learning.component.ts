import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, ElementRef, OnDestroy, OnInit, ViewChild, ViewEncapsulation, inject } from '@angular/core';
import { Subscription } from 'rxjs';
import { LearningChapter, LearningContent, LearningManifest, TRADING_CHECKLIST, TradingCheckGroup } from './learning.types';

const STORAGE_KEY = 'traders-gita-learning-v1';

@Component({ selector: 'app-learning', standalone: true, imports: [CommonModule],
  templateUrl: './learning.component.html', styleUrl: './learning.component.css', encapsulation: ViewEncapsulation.None })
export class LearningComponent implements OnInit, OnDestroy {
  private readonly http = inject(HttpClient);
  private libraryRequest?: Subscription;
  private chapterRequest?: Subscription;
  private scrollTimer?: ReturnType<typeof setTimeout>;
  @ViewChild('chapterBody') chapterBody?: ElementRef<HTMLElement>;
  @ViewChild('reader') reader?: ElementRef<HTMLElement>;
  readonly assetBase = 'assets/learning/';
  manifest: LearningManifest | null = null;
  content: LearningContent | null = null;
  view: 'chapters' | 'checklist' = 'chapters';
  selectedId = '';
  search = '';
  category = '';
  loading = true;
  chapterLoading = false;
  error = '';
  chapterError = '';
  storageError = false;
  read = new Set<string>();
  checked = new Set<string>();
  optionsTrade = true;
  notes = '';

  ngOnInit(): void { this.restore(); this.loadLibrary(); }
  ngOnDestroy(): void { this.libraryRequest?.unsubscribe(); this.chapterRequest?.unsubscribe(); clearTimeout(this.scrollTimer); }
  loadLibrary(): void {
    this.libraryRequest?.unsubscribe(); this.loading = true; this.error = '';
    this.libraryRequest = this.http.get<LearningManifest>(this.assetBase + 'manifest.json').subscribe({
      next: manifest => {
        this.manifest = manifest; this.loading = false;
        const validIds = new Set(manifest.chapters.map(c => c.id));
        this.read = new Set([...this.read].filter(id => validIds.has(id)));
        this.openChapter(validIds.has(this.selectedId) ? this.selectedId : manifest.chapters[0].id, true);
      },
      error: () => { this.loading = false; this.error = 'The learning library could not load. Please retry.'; }
    });
  }
  get chapters(): LearningChapter[] { return this.manifest?.chapters ?? []; }
  get categories(): string[] { return [...new Set(this.chapters.map(c => c.category))]; }
  get selected(): LearningChapter | undefined { return this.chapters.find(c => c.id === this.selectedId); }
  get selectedIndex(): number { return this.chapters.findIndex(c => c.id === this.selectedId); }
  get progress(): number { return this.chapters.length ? Math.round(this.read.size / this.chapters.length * 100) : 0; }
  get filteredChapters(): LearningChapter[] {
    const words = this.search.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    return this.chapters.filter(c => (!this.category || c.category === this.category) &&
      words.every(word => `${c.title} ${c.category} ${c.searchText}`.toLocaleLowerCase().includes(word)));
  }
  get chapterGroups(): { title: string; chapters: LearningChapter[] }[] {
    const filtered = this.filteredChapters;
    return this.categories.map(title => ({ title, chapters: filtered.filter(c => c.category === title) })).filter(g => g.chapters.length);
  }
  get sections() { return this.content?.headings.filter(h => h.level <= 3) ?? []; }
  trackChapter(_index: number, chapter: LearningChapter): string { return chapter.id; }
  openChapter(id: string, keepView = false): void {
    if (!this.chapters.some(c => c.id === id)) return;
    if (!keepView) {
      if (this.view === 'checklist') this.clearSearch();
      this.view = 'chapters';
      clearTimeout(this.scrollTimer);
      this.scrollTimer = setTimeout(() => this.reader?.nativeElement.scrollIntoView({ behavior: 'smooth', block: 'start' }), 0);
    }
    this.selectedId = id; this.content = null; this.chapterError = ''; this.chapterLoading = true;
    this.chapterRequest?.unsubscribe(); this.save();
    this.chapterRequest = this.http.get<LearningContent>(this.assetBase + id + '.json').subscribe({
      next: content => { this.content = content; this.chapterLoading = false; },
      error: () => { this.chapterLoading = false; this.chapterError = 'This chapter could not load. Please retry.'; }
    });
  }
  changeView(view: 'chapters' | 'checklist'): void { this.view = view; this.save(); }
  toggleRead(): void {
    if (this.read.has(this.selectedId)) this.read.delete(this.selectedId); else this.read.add(this.selectedId);
    this.save();
  }
  nextChapter(offset: number): void { const chapter = this.chapters[this.selectedIndex + offset]; if (chapter) this.openChapter(chapter.id); }
  jumpTo(id: string): void {
    if (!/^section-\d+$/.test(id)) return;
    const index = this.content?.headings.findIndex(h => h.id === id) ?? -1;
    // Angular removes id attributes from sanitized innerHTML. Use the source
    // heading order, retaining sanitization rather than trusting document HTML.
    if (index >= 0) this.chapterBody?.nativeElement.querySelectorAll<HTMLElement>('h2, h3, h4')[index]?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  clearSearch(): void { this.search = ''; this.category = ''; }
  excerpt(chapter: LearningChapter): string {
    const term = this.search.trim().toLocaleLowerCase().split(/\s+/)[0];
    if (!term) return '';
    const text = chapter.searchText.replace(/\s+/g, ' ');
    const index = text.toLocaleLowerCase().indexOf(term);
    if (index < 0) return '';
    const start = Math.max(0, index - 45);
    return (start ? '…' : '') + text.slice(start, index + 100) + '…';
  }

  get checklistGroups(): TradingCheckGroup[] { return TRADING_CHECKLIST.filter(g => !g.optionsOnly || this.optionsTrade); }
  get checkCount(): number { return this.checklistGroups.reduce((n, g) => n + g.items.length, 0); }
  get completedChecks(): number { return this.checklistGroups.reduce((n, g) => n + this.groupDone(g), 0); }
  get requiredLeft(): number { return this.checklistGroups.flatMap(g => g.items).filter(i => i.required && !this.checked.has(i.id)).length; }
  groupDone(group: TradingCheckGroup): number { return group.items.filter(i => this.checked.has(i.id)).length; }
  check(id: string, value: boolean): void { if (value) this.checked.add(id); else this.checked.delete(id); this.save(); }
  setOptions(value: boolean): void { this.optionsTrade = value; this.save(); }
  setNotes(value: string): void { this.notes = value.slice(0, 10000); this.save(); }
  resetChecks(): void { this.checked.clear(); this.save(); }
  chapterTitle(id: string): string { return this.chapters.find(c => c.id === id)?.title ?? 'Read chapter'; }
  private restore(): void {
    try {
      const data = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null');
      if (!data || typeof data !== 'object') return;
      this.read = new Set(Array.isArray(data.read) ? data.read.filter((x: unknown) => typeof x === 'string') : []);
      const ids = new Set(TRADING_CHECKLIST.flatMap(g => g.items.map(i => i.id)));
      this.checked = new Set(Array.isArray(data.checked) ? data.checked.filter((x: unknown) => typeof x === 'string' && ids.has(x)) : []);
      this.selectedId = typeof data.selectedId === 'string' ? data.selectedId : '';
      this.optionsTrade = data.optionsTrade !== false;
      this.view = data.view === 'checklist' ? 'checklist' : 'chapters';
      this.notes = typeof data.notes === 'string' ? data.notes.slice(0, 10000) : '';
    } catch { this.storageError = true; }
  }
  private save(): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ read: [...this.read], checked: [...this.checked],
        selectedId: this.selectedId, optionsTrade: this.optionsTrade, view: this.view, notes: this.notes }));
      this.storageError = false;
    } catch { this.storageError = true; }
  }
}
