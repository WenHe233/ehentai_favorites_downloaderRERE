import axios from "axios";
import useSWR from "swr";
import api, { useApiBaseUrl } from "./api";
export function useApi<T>(path: string | null, refreshInterval = 0) {
  const base = useApiBaseUrl();
  return useSWR<T>(
    path ? [base, path] : null,
    async ([, url]: [string, string]) => (await api.get<T>(url)).data,
    { refreshInterval, revalidateOnFocus: true },
  );
}
export function errorText(error: unknown) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (Array.isArray(detail)) return detail.map((item) => item.msg).join("；");
    return typeof detail === "string" ? detail : error.message;
  }
  return error instanceof Error ? error.message : "操作失败，请重试";
}
export function dateText(value?: string | null) {
  if (!value) return "—";
  const iso = value.replace(" ", "T");
  const date = new Date(/Z$|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + "Z");
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
