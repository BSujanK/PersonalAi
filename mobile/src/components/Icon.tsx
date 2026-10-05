import Feather from '@expo/vector-icons/Feather';
import type { ComponentProps } from 'react';

import { useTheme } from '../theme';

export type IconName = ComponentProps<typeof Feather>['name'];

/** Decorative by default: the pressable around it carries the accessibility label. */
export function Icon({
  name,
  size = 20,
  color,
}: {
  name: IconName;
  size?: number;
  color?: string;
}) {
  const { palette } = useTheme();
  return (
    <Feather
      name={name}
      size={size}
      color={color ?? palette.text}
      accessible={false}
      importantForAccessibility="no"
    />
  );
}
