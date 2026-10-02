const AUTH_TOKEN_KEY = "eh_auth_token";

export const getAuthToken = (): string | null => {
  return window.localStorage.getItem(AUTH_TOKEN_KEY);
};

export const setAuthToken = (token: string) => {
  window.localStorage.setItem(AUTH_TOKEN_KEY, token);
};

export const clearAuthToken = () => {
  window.localStorage.removeItem(AUTH_TOKEN_KEY);
};

export const notifyAuthUnauthorized = () => {
  window.dispatchEvent(new Event("auth:unauthorized"));
};
