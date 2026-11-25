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
  Pressable,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { MAX_BOLT_SPACING_CM, MIN_BOLT_SPACING_CM } from '@/utils/boltSpacing'
import {
  BOLT_PATTERNS,
  BoltPattern,
  toMeasuredCm,
  toSquareSideCm,
} from '@/utils/boltPattern'
import { BoltPatternGraphic } from './BoltPatternGraphic'
import {
  ClimberStats,
  MAX_CLIMBER_ARM_SPAN_CM,
  MAX_CLIMBER_HEIGHT_CM,
  MIN_CLIMBER_ARM_SPAN_CM,
  MIN_CLIMBER_HEIGHT_CM,
  parseOptionalCm,
} from '@/utils/climberStats'

//Scrollable settings panel opened from CameraScreen: bolt spacing, plus the
//climber's height and arm span (optional, slice 15) - new settings go inside
//the ScrollView.

type SettingsModalProps = {
  visible: boolean
  boltSpacingCm: number
  boltPattern: BoltPattern
  //squareSideCm is always the side of a square with a centre hole (see utils/boltPattern.ts).
  onSave: (squareSideCm: number, pattern: BoltPattern) => void
  climberStats: ClimberStats
  onSaveClimberStats: (stats: ClimberStats) => void
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

function SettingsForm({
  boltSpacingCm,
  boltPattern,
  onSave,
  climberStats,
  onSaveClimberStats,
  onClose,
}: Omit<SettingsModalProps, 'visible'>) {
  //Draft text so the user can type freely - only valid values are saved.
  //The spacing field holds what the user measures for the chosen pattern;
  //switching pattern keeps the typed number (they measure their own wall).

  const [pattern, setPattern] = useState<BoltPattern>(boltPattern)
  const [draft, setDraft] = useState(String(toMeasuredCm(boltSpacingCm, boltPattern)))
  const [heightDraft, setHeightDraft] = useState(
    climberStats.heightCm === null ? '' : String(climberStats.heightCm)
  )
  const [spanDraft, setSpanDraft] = useState(
    climberStats.armSpanCm === null ? '' : String(climberStats.armSpanCm)
  )

  const selected = BOLT_PATTERNS.find((p) => p.id === pattern) ?? BOLT_PATTERNS[0]
  const measured = draft.trim() === '' ? NaN : Number(draft.trim().replace(',', '.'))
  const side = Number.isFinite(measured) ? toSquareSideCm(measured, pattern) : NaN
  const parsed = side >= MIN_BOLT_SPACING_CM && side <= MAX_BOLT_SPACING_CM ? side : null
  //The allowed range in the units the user is typing, for the error message.
  const minMeasured = Math.ceil((MIN_BOLT_SPACING_CM / selected.factor) * 10) / 10
  const maxMeasured = Math.floor((MAX_BOLT_SPACING_CM / selected.factor) * 10) / 10
  const height = parseOptionalCm(heightDraft, MIN_CLIMBER_HEIGHT_CM, MAX_CLIMBER_HEIGHT_CM)
  const span = parseOptionalCm(spanDraft, MIN_CLIMBER_ARM_SPAN_CM, MAX_CLIMBER_ARM_SPAN_CM)
  const valid = parsed !== null && height.ok && span.ok

  const save = () => {
    if (parsed === null || !height.ok || !span.ok) return
    onSave(parsed, pattern)
    onSaveClimberStats({ heightCm: height.value, armSpanCm: span.value })
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
          <Text style={styles.label}>Bolt hole pattern</Text>
          <Text style={styles.help}>
            Pick the one that looks like your wall&apos;s bolt holes. The app uses them as a ruler to
            measure the wall and the distance between holds.
          </Text>
          <View style={styles.patternRow}>
            {BOLT_PATTERNS.map((p) => (
              <Pressable
                key={p.id}
                onPress={() => setPattern(p.id)}
                style={[styles.patternCard, p.id === pattern && styles.patternCardSelected]}
                accessibilityRole="radio"
                accessibilityState={{ selected: p.id === pattern }}
                accessibilityLabel={p.label}
              >
                <BoltPatternGraphic pattern={p.id} />
                <Text style={styles.patternLabel}>{p.label}</Text>
              </Pressable>
            ))}
          </View>

          <Text style={[styles.label, styles.sectionGap]}>Bolt hole spacing (cm)</Text>
          <Text style={styles.help}>{selected.measure} The orange line in the picture shows it.</Text>
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
              Enter a number between {minMeasured} and {maxMeasured}.
            </Text>
          )}

          <Text style={[styles.label, styles.sectionGap]}>Your height (cm, optional)</Text>
          <TextInput
            style={styles.input}
            value={heightDraft}
            onChangeText={setHeightDraft}
            keyboardType="decimal-pad"
            returnKeyType="done"
            placeholder="e.g. 175"
          />
          {!height.ok && (
            <Text style={styles.errorText}>
              Enter a number between {MIN_CLIMBER_HEIGHT_CM} and {MAX_CLIMBER_HEIGHT_CM}, or leave
              it empty.
            </Text>
          )}

          <Text style={styles.label}>Your arm span (cm, optional)</Text>
          <Text style={styles.help}>
            Fingertip to fingertip with your arms stretched out to the sides. With your height, it
            lets the coach judge which moves are a stretch for you.
          </Text>
          <TextInput
            style={styles.input}
            value={spanDraft}
            onChangeText={setSpanDraft}
            keyboardType="decimal-pad"
            returnKeyType="done"
            placeholder="e.g. 178"
          />
          {!span.ok && (
            <Text style={styles.errorText}>
              Enter a number between {MIN_CLIMBER_ARM_SPAN_CM} and {MAX_CLIMBER_ARM_SPAN_CM}, or
              leave it empty.
            </Text>
          )}
        </ScrollView>
        <View style={styles.buttonsRow}>
          <Button title="Cancel" onPress={onClose} />
          <Button title="Save" onPress={save} disabled={!valid} />
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
  sectionGap: {
    marginTop: 16,
  },
  patternRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  patternCard: {
    flexBasis: '30%',
    flexGrow: 1,
    alignItems: 'center',
    padding: 8,
    borderWidth: 2,
    borderColor: '#ddd',
    borderRadius: 8,
  },
  patternCardSelected: {
    borderColor: '#ff8c00',
    backgroundColor: '#fff4e6',
  },
  patternLabel: {
    marginTop: 4,
    textAlign: 'center',
    fontSize: 13,
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
