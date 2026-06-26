// Cryptographically-random password generator for the "genera password" buttons.
// Ambiguous characters (I, O, 0, 1, l) are excluded for readability.
const CHARSET = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789@#$%&'

export function generatePassword(length = 8): string {
  const arr = new Uint32Array(length)
  crypto.getRandomValues(arr)
  return Array.from(arr, (n) => CHARSET[n % CHARSET.length]).join('')
}
