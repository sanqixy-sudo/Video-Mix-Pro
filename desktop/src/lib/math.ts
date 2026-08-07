export function nPermK(n: number, k: number): number {
  if (k > n || k < 0) return 0;
  let result = 1;
  for (let i = 0; i < k; i += 1) result *= n - i;
  return result;
}

export function maxUniqueCount(n: number, k: number, allowRepeatInsideOneVideo: boolean): number {
  if (k <= 0 || n <= 0) return 0;
  if (allowRepeatInsideOneVideo) return n ** k;
  return nPermK(n, k);
}

export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return "-";
  return Math.round(value).toLocaleString("en-US");
}
