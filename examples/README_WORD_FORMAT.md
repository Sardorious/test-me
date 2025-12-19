# Word Upload Format Guide

This guide explains how to format word files for uploading to the bot.

## Supported File Formats
- `.txt` (Plain text files)
- `.docx` (Microsoft Word documents)

## Format Rules

### Basic Format
Each line should contain one word pair in the following format:
```
turkish_word - uzbek_translation
```

### Multiple Translations
You can specify multiple correct translations for a word by separating them with semicolons (`;`):
```
turkish_word - uzbek_translation1; uzbek_translation2; uzbek_translation3
```

### Important Notes:
1. **Separator**: Use a single dash (`-`) with spaces on both sides to separate Turkish and Uzbek words
2. **Multiple translations**: Use semicolon (`;`) to separate multiple correct answers (2-3 translations recommended)
3. **One word per line**: Each line should contain only one word pair
4. **No empty lines**: Skip empty lines (they will be ignored)
5. **Case insensitive**: Turkish and Uzbek words can be in any case
6. **Special characters**: Turkish characters (ç, ğ, ı, ö, ş, ü) and Uzbek characters (o', g', ch, sh) are supported

## Examples

### Correct Format:
```
merhaba - salom
teşekkür ederim - rahmat
günaydın - xayrli tong
merhaba - salom; assalomu alaykum
iyi - yaxshi; yaxshimisiz
```

### Incorrect Formats:
```
merhaba-salom          ❌ (no spaces around dash)
merhaba  -  salom      ❌ (multiple spaces - will work but not recommended)
merhaba salom          ❌ (no dash separator)
merhaba - salom - ...  ❌ (multiple dashes)
```

## File Organization

### By CEFR Level
Organize your word files by CEFR level:
- `words_A1.txt` - Beginner level words
- `words_A2.txt` - Elementary level words
- `words_B1.txt` - Intermediate level words
- `words_B2.txt` - Upper-intermediate level words
- `words_C1.txt` - Advanced level words
- `words_C2.txt` - Proficient level words

### By Topic (Optional)
You can also organize by topic:
- `words_food_A1.txt` - Food vocabulary at A1 level
- `words_travel_A2.txt` - Travel vocabulary at A2 level
- `words_business_B1.txt` - Business vocabulary at B1 level

## Example Files

See the example files in the `examples/` directory:
- `words_example_A1.txt` - A1 level example
- `words_example_A2.txt` - A2 level example
- `words_example_B1.txt` - B1 level example

## Upload Process

1. Prepare your word file following the format above
2. Use the `/upload_words` command in the bot
3. Select the CEFR level (A1, A2, B1, B2, C1, C2)
4. Upload your `.txt` or `.docx` file
5. The bot will parse and save all valid word pairs

## Tips

- **Start small**: Begin with 20-50 words to test the format
- **Check spelling**: Make sure Turkish and Uzbek words are spelled correctly
- **Use consistent format**: Keep the same format throughout the file
- **Remove duplicates**: The bot may skip duplicate words
- **Test first**: Upload a small test file before uploading large word lists

