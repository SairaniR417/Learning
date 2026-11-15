import { AfterViewChecked, Directive, ElementRef, EventEmitter, HostListener, Input, OnChanges, Output, inject } from '@angular/core';

/** Small native-control binding; this app does not depend on Angular Forms. */
@Directive({ selector: 'input[researchValue],select[researchValue],textarea[researchValue]', standalone: true })
export class ResearchValueDirective implements OnChanges, AfterViewChecked {
  @Input() researchValue: string | number = '';
  @Output() researchValueChange = new EventEmitter<any>();
  private element = inject<ElementRef<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>>(ElementRef);
  ngOnChanges(): void { this.element.nativeElement.value = String(this.researchValue ?? ''); }
  ngAfterViewChecked(): void { const value = String(this.researchValue ?? ''); if (this.element.nativeElement.value !== value) this.element.nativeElement.value = value; }
  @HostListener('input') input(): void { const el = this.element.nativeElement; this.researchValueChange.emit(el instanceof HTMLInputElement && el.type === 'number' ? el.valueAsNumber : el.value); }
}
