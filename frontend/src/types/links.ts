export interface CreateLinkRequest {
  url: string;
  expires_at: string | null;
}

export interface CreatedLink {
  code: string;
  short_url: string;
  original_url: string;
  created_at: string;
  expires_at: string | null;
}

export interface LinkStats {
  code: string;
  total_clicks: number;
  clicks_last_24_hours: number;
  created_at: string;
  expires_at: string | null;
}

export interface ApiErrorBody {
  detail?: unknown;
  error?: {
    code?: string;
    message?: string;
    details?: Array<{ field: string; message: string }>;
  };
}
