import { dimensionPresentation } from './billingDimensions';
import './BillingDimensions.css';

export default function BillingDimensionValue({ value, kind, required = false }) {
  const presentation = dimensionPresentation(value, kind, { required });
  return (
    <span
      className={`billing-dimension-value billing-dimension-value--${presentation.state}`}
      title={presentation.raw || presentation.text}
    >
      {presentation.text}
    </span>
  );
}
