/**
 * Barrel export for @briefed/ui primitives.
 *
 * Phase 6 lands the complete set referenced in plan §10 + §19.16. Feature
 * code must only import from here — a root lint rule forbids styled
 * primitives from outside this package.
 */

export { Alert, type AlertProps, type AlertTone } from './primitives/Alert';
export { Badge, type BadgeProps, type BadgeTone } from './primitives/Badge';
export { Button, type ButtonProps, type ButtonSize, type ButtonVariant } from './primitives/Button';
export { Card, type CardProps } from './primitives/Card';
export { Dialog, type DialogProps } from './primitives/Dialog';
export { EmptyState, type EmptyStateProps } from './primitives/EmptyState';
export { ErrorState, type ErrorStateProps } from './primitives/ErrorState';
export { Field, type FieldProps } from './primitives/Field';
export {
  FreshnessBadge,
  type FreshnessBadgeProps,
  type FreshnessState,
} from './primitives/FreshnessBadge';
export { InstallPromptIOS, type InstallPromptIOSProps } from './primitives/InstallPromptIOS';
export { Motion, type MotionProps } from './primitives/Motion';
export { OpenInGmailLink, type OpenInGmailLinkProps } from './primitives/OpenInGmailLink';
export { Sheet, type SheetProps } from './primitives/Sheet';
export { Skeleton, type SkeletonProps } from './primitives/Skeleton';
export { Switch, type SwitchProps } from './primitives/Switch';
export { WhyBadge, type DecisionSource, type WhyBadgeProps } from './primitives/WhyBadge';
