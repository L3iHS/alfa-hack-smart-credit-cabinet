import type { DeclineReason } from "../api/types";
export const reasonLabels: Record<DeclineReason, string> = {
  insufficient_amount: 'Недостаточная сумма', high_payment: 'Высокий платёж',
  unsuitable_term: 'Не подходит срок', no_longer_needed: 'Больше не требуется', other: 'Другая причина',
};
