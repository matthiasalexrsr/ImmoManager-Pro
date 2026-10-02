/** Preserve the server's correctable OCR code/message; never turn upload into failure. */
export function ocrFailure(error, t) {
  const detail = error?.detail || error?.ocr_error || error;
  const code = typeof detail?.code === 'string' && /^ocr_[a-z_]+$/.test(detail.code) ? detail.code : null;
  const message = typeof detail?.message === 'string' && detail.message.trim()
    ? detail.message : t('documentsOCR.unavailable');
  const category = code?.endsWith('_budget') ? 'budget'
    : code === 'ocr_timeout' ? 'timeout'
    : ['ocr_tool_missing', 'ocr_tool_unavailable', 'ocr_language_missing', 'ocr_image_dependency_missing', 'ocr_config_invalid'].includes(code) ? 'setup'
    : ['ocr_invalid_image', 'ocr_invalid_pdf', 'ocr_render_failed', 'ocr_tesseract_failed'].includes(code) ? 'original'
    : 'worker';
  return { success: false, message, code, correction: t(`documentsOCR.corrections.${category}`),
    httpStatus: Number.isInteger(error?.statusCode) ? error.statusCode : null };
}
