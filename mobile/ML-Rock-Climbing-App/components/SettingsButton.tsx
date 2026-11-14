import { StyleSheet, Text, TouchableOpacity } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

//Top-right gear that opens SettingsModal - shared by CameraScreen and PhotoPreview.

type SettingsButtonProps = {
  onPress: () => void
}

export function SettingsButton({ onPress }: SettingsButtonProps) {
  const insets = useSafeAreaInsets()

  return (
    <TouchableOpacity
      style={[styles.button, { top: insets.top + 12 }]}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel="Settings"
    >
      <Text style={styles.icon}>⚙</Text>
    </TouchableOpacity>
  )
}

const styles = StyleSheet.create({
  button: {
    position: 'absolute',
    right: 16,
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: 'rgba(0, 0, 0, 0.4)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  icon: {
    color: 'white',
    fontSize: 24,
  },
})
