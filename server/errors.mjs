export class HttpError extends Error {
  constructor(statusCode, message, code = "request_error") {
    super(message);
    this.name = "HttpError";
    this.statusCode = statusCode;
    this.code = code;
  }
}

export function publicError(error) {
  if (error instanceof HttpError) {
    return {
      statusCode: error.statusCode,
      body: { error: { code: error.code, message: error.message } },
    };
  }

  return {
    statusCode: 500,
    body: {
      error: {
        code: error?.code || "internal_error",
        message: error?.message || "Unexpected server error",
      },
    },
  };
}
