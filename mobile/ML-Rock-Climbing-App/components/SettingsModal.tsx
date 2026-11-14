import { useState } from 'react'
import {
  Modal,
  View,
  Text,
  TextInput,
  Button,
  ScrollView,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { MAX_BOLT_SPACING_CM, MIN_BOLT_SPACING_CM, parseBoltSpacing } from '@/utils/boltSpacing'

//Scrollable settings panel opened from CameraScreen. Only bolt spacing for
//now - new settings go inside the ScrollView.

type SettingsModalProps = {
  visible: boolean
  boltSpacingCm: number
  onSave: (boltSpacingCm: number) => void
  onClose: () => void
}

export function SettingsModal({ visible, ...formProps }: SettingsModalProps) {
  //The form only mounts while open, so each opening starts its draft from
  //the saved value instead of whatever was left unsaved last time.

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={formProps.onClose}>
      {visible && <SettingsForm {...formProps} />}
    </Modal>
  )
}

function SettingsForm({ boltSpacingCm, onSave, onClose }: Omit<SettingsModalProps, 'visible'>) {
  //Draft text so the user can type freely - only a valid value is saved.

  const [draft, setDraft] = useState(String(boltSpacingCm))

  const parsed = parseBoltSpacing(draft)

  const save = () => {
    if (parsed === null) return
    onSave(parsed)
    onClose()
  }

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView
        style={styles.container}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <Text style={styles.title}>Settings</Text>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <Text style={styles.label}>Bolt hole spacing (cm)</Text>
          <Text style={styles.help}>
            The side length of one square in your gym&apos;s bolt-hole grid (the distance between
            two neighbouring corner holes, not to the centre hole). Used to measure the wall and the
            distance between holds.
          </Text>
          <TextInput
            style={styles.input}
            value={draft}
            onChangeText={setDraft}
            keyboardType="decimal-pad"
            returnKeyType="done"
            onSubmitEditing={save}
          />
          {parsed === null && (
            <Text style={styles.errorText}>
              Enter a number between {MIN_BOLT_SPACING_CM} and {MAX_BOLT_SPACING_CM}.
            </Text>
          )}
        </ScrollView>
        <View style={styles.buttonsRow}>
          <Button title="Cancel" onPress={onClose} />
          <Button title="Save" onPress={save} disabled={parsed === null} />
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  title: {
    fontSize: 22,
    fontWeight: 'bold',
    paddingHorizontal: 20,
    paddingTop: 16,
  },
  content: {
    padding: 20,
    gap: 8,
  },
  label: {
    fontSize: 16,
    fontWeight: '600',
  },
  help: {
    color: '#555',
  },
  input: {
    borderWidth: 1,
    borderColor: '#999',
    borderRadius: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    fontSize: 16,
  },
  errorText: {
    color: 'red',
  },
  buttonsRow: {
    flexDirection: 'row',
    justifyContent: 'space-evenly',
    paddingVertical: 12,
  },
})
