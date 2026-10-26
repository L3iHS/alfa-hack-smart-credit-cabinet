import type { CompletionKind, DealOutput } from "../api/types";

export const completionLabels: Record<CompletionKind, string> = {
  credit: "Кредит выдан",
  limit: "Лимит открыт",
  guarantee: "Гарантия выпущена",
};

export function dealStatusLabel(deal: DealOutput | null | undefined) {
  if (!deal) return "Ожидает оформления";
  if (deal.status === "completed") return completionLabels[deal.completion_kind];
  return {
    prepared: "Условия подготовлены",
    confirmed: "Условия подтверждены",
    cancelled: "Оформление отменено",
  }[deal.status];
}

export default function DealStatus({ deal }: { deal?: DealOutput | null }) {
  return <span className={`deal-status deal-status-${deal?.status || "waiting"}`}>{dealStatusLabel(deal)}</span>;
}
