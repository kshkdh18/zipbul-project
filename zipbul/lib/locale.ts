import {messages} from './messages';
import {demoTranslations} from './demo-translations';
export type Locale = 'en' | 'ko';
export const DEFAULT_LOCALE: Locale = 'en';
export function translate(text: string | null | undefined, locale: Locale = DEFAULT_LOCALE, ...args: unknown[]): string {
  if(text == null) return '';
  const source = String(text);
  let result = locale === 'ko' ? source : (messages[source] ?? demoTranslations[source] ?? source);
  if(locale === 'en' && result === source) {
    result = result.replace(/^근거 검증 (\d+\/\d+) 프레임$/, 'Checking evidence $1 frames')
      .replace(/^원본 프레임 관찰 (\d+\/\d+)$/, 'Observing source frames $1')
      .replace(/^Sites 자료 저장 (\d+)%$/, 'Saving cloud assets $1%');
  }
  return result.replace(/\{(\d+)\}/g, (_, index) => translate(String(args[Number(index)] ?? ''), locale));
}
