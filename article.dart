import 'package:flutter/material.dart';
// import 'package:flutter_html/flutter_html.dart'; // Unused import
import 'package:webfeed/webfeed.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:html/parser.dart' as html_parser;

import './interactive_translator_widget.dart';
import './dictionary_service.dart';

// Helper class to hold parts for a single sentence and its translation
class SentenceTranslationUnit {
  String id; // Unique ID for Key
  List<String> spanishParts; // Words and punctuation of the Spanish sentence
  List<String> englishParts; // Corresponding English words, placeholders, or punctuation

  SentenceTranslationUnit({
    required this.id,
    required this.spanishParts,
    required this.englishParts,
  });

  String get spanishSentenceText => spanishParts.join(' ');
}

class ArticleDetailScreen extends StatefulWidget {
  final RssItem article;

  const ArticleDetailScreen({super.key, required this.article});

  @override
  ArticleDetailScreenState createState() => ArticleDetailScreenState();
}

class ArticleDetailScreenState extends State<ArticleDetailScreen> {
  final ScrollController _scrollController = ScrollController();
  final DictionaryService _dictionaryService = DictionaryService();
  bool _isDictionaryReady = false;

  List<SentenceTranslationUnit> _translationUnits = [];
  bool _isContentPrepped = false;
  bool _isTranslatingInProgress = false;
  String? _contentError;

  @override
  void initState() {
    super.initState();
    _initAndPrepareContentForTranslation();
  }

  Future<void> _initAndPrepareContentForTranslation() async {
    if (!mounted) return;
    setState(() {
      _isContentPrepped = false;
      _isTranslatingInProgress = true; // Initial prep is part of overall translation
      _contentError = null;
    });

    try {
      await _dictionaryService.database;
      if (mounted) {
        setState(() {
          _isDictionaryReady = true;
        });
      }

      final String? rawArticleContent = widget.article.content?.value ?? widget.article.description;
      if (rawArticleContent == null || rawArticleContent.trim().isEmpty) {
        if (mounted) {
          setState(() {
            _contentError = "No content available for this article.";
            _isContentPrepped = true;
            _isTranslatingInProgress = false;
          });
        }
        return;
      }

      final String plainText = _parseHtmlToPlainText(rawArticleContent);
      if (plainText.isEmpty) {
        if (mounted) {
          setState(() {
            _contentError = "(Content is empty after HTML stripping)";
            _isContentPrepped = true;
            _isTranslatingInProgress = false;
          });
        }
        return;
      }

      _segmentTextAndSetPlaceholders(plainText);

      if (mounted) {
        setState(() {
          _isContentPrepped = true; // Now the UI can build with placeholders
        });
        // A small delay to ensure UI renders placeholders before intensive translation starts
        await Future.delayed(const Duration(milliseconds: 200)); 
        if (mounted) {
          _beginProgressiveWordTranslation();
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _contentError = "Error during content preparation: ${e.toString()}";
          _isContentPrepped = true; // Allow UI to show error
          _isTranslatingInProgress = false;
        });
      }
      // Consider using a logger instead of print
      // print("Error in _initAndPrepareContentForTranslation: $e");
    }
  }

  String _parseHtmlToPlainText(String? htmlString) {
    if (htmlString == null || htmlString.trim().isEmpty) return '';
    try {
      final document = html_parser.parse(htmlString);
      String text = document.body?.text ?? '';
      // Normalize whitespace: replace multiple spaces/newlines with a single space
      text = text.replaceAll(RegExp(r'\s+'), ' ').trim();
      return text;
    } catch (e) {
      // Consider using a logger instead of print
      // print("Failed to parse HTML: $htmlString, Error: $e");
      return htmlString; // Fallback to original if parsing fails
    }
  }

  void _segmentTextAndSetPlaceholders(String plainText) {
    _translationUnits = [];
    // This regex attempts to split after a sentence-ending punctuation mark (.!?)
    // followed by whitespace, and then an uppercase letter or an opening Spanish punctuation mark.
    // It also includes splitting on one or more newline characters as a fallback.
    final List<String> sentences = plainText.split(RegExp(r'(?<=[.!?])\s+(?=[A-Z\u00BF\u00A1])|\n+')); // Fixing syntax error in regex pattern

    final RegExp wordOrPunctuationRegex = RegExp(r"([\wÀ-ÖØ-öø-ÿ]+(?:['’][\wÀ-ÖØ-öø-ÿ]+)*|[.,!?;:])");
    int sentenceIdCounter = 0;

    for (String sentenceText in sentences) {
      if (sentenceText.trim().isEmpty) continue;

      List<String> currentSpanishParts = [];
      List<String> currentEnglishParts = [];
      final Iterable<Match> matches = wordOrPunctuationRegex.allMatches(sentenceText);

      for (Match match in matches) {
        String part = match.group(0)!;
        currentSpanishParts.add(part);
        if (RegExp(r"^[\wÀ-ÖØ-öø-ÿ]").hasMatch(part)) { // If it starts like a word
          currentEnglishParts.add("(Translating...)");
        } else { // Punctuation
          currentEnglishParts.add(part);
        }
      }
      
      if (currentSpanishParts.isNotEmpty) {
        _translationUnits.add(SentenceTranslationUnit(
          id: 'sentence_${sentenceIdCounter++}',
          spanishParts: currentSpanishParts,
          englishParts: currentEnglishParts,
        ));
      }
    }
  }

  Future<void> _beginProgressiveWordTranslation() async {
    if (!_isDictionaryReady || !mounted) {
      if(mounted) setState(() => _isTranslatingInProgress = false);
      return;
    }
    if(!mounted) return; // double check
    setState(() => _isTranslatingInProgress = true);


    for (int i = 0; i < _translationUnits.length; i++) {
      if (!mounted) return; 
      SentenceTranslationUnit unit = _translationUnits[i];

      for (int j = 0; j < unit.spanishParts.length; j++) {
        if (!mounted) return;
        String spanishWord = unit.spanishParts[j];
        
        // Only translate if it's a placeholder
        if (unit.englishParts[j] == "(Translating...)") {
          try {
            String? translatedWord = await _dictionaryService.translate(spanishWord.toLowerCase());
            if (mounted) {
              setState(() {
                // Ensure the unit is still the same in the list if list could change
                 _translationUnits[i].englishParts[j] = translatedWord ?? spanishWord; 
              });
            }
          } catch (e) {
            // Consider using a logger instead of print
            // print("Error translating word '$spanishWord': $e");
            if (mounted) {
              setState(() {
                _translationUnits[i].englishParts[j] = spanishWord; // Fallback to original
              });
            }
          }
          // Delay to make updates visible and not overwhelm the UI thread
          if (mounted) {
             await Future.delayed(const Duration(milliseconds: 75)); // Adjust timing as needed
          }
        }
      }
    }

    if (mounted) {
      setState(() => _isTranslatingInProgress = false);
    }
  }
  
  @override
  void dispose() {
    _scrollController.dispose();
    _dictionaryService.close();
    super.dispose();
  }

  Future<void> _launchOriginalArticleUrl(String? urlString) async {
    if (urlString == null || urlString.isEmpty) {
        if(mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('No URL available for this article.')));
        return;
    }
    final Uri url = Uri.parse(urlString);
    if (!await launchUrl(url, mode: LaunchMode.externalApplication)) {
      // Consider using a logger instead of print
      // print('Could not launch $urlString');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not open link: $urlString')),
        );
      }
    }
  }

  void _showInteractiveTranslator() {
    final String articleText = _translationUnits.map((u) => u.spanishSentenceText).join('\n\n'); // Fixing syntax error in string concatenation
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (BuildContext context) {
        return InteractiveTranslatorWidget(text: articleText);
      },
    );
  }

  // UI Rendering
  Widget _buildTranslatedArticleView(BuildContext context) {
    if (!_isContentPrepped && _isTranslatingInProgress) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_contentError != null) {
      return Center(child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Text(_contentError!, style: TextStyle(color: Colors.red.shade700, fontSize: 16)),
      ));
    }
     if (_translationUnits.isEmpty && !_isTranslatingInProgress) {
      return const Center(child: Padding(
        padding: EdgeInsets.all(16.0),
        child: Text("No translatable sentences found in the article.", style: TextStyle(fontSize: 16)),
      ));
    }

    return ListView.builder(
      shrinkWrap: true, 
      physics: const NeverScrollableScrollPhysics(), 
      itemCount: _translationUnits.length,
      itemBuilder: (context, index) {
        final unit = _translationUnits[index];
        
        List<TextSpan> englishLineSpans = [];
        for (int k = 0; k < unit.englishParts.length; k++) {
            String part = unit.englishParts[k];
            String spanishPart = unit.spanishParts[k]; // To ensure space is added correctly for punctuation
            bool isPlaceholder = part == "(Translating...)";
            
            englishLineSpans.add(TextSpan(
                text: part,
                style: TextStyle(
                    fontSize: Theme.of(context).textTheme.bodyMedium?.fontSize ?? 15.0,
                    color: isPlaceholder 
                        ? Colors.grey.shade500 
                        : Theme.of(context).colorScheme.primary,
                    fontStyle: isPlaceholder ? FontStyle.italic : FontStyle.normal,
                )
            ));
            // Add a space if the original Spanish part was a word, or if the English part (punctuation) doesn't end with space
            if (RegExp(r"[\wÀ-ÖØ-öø-ÿ]$").hasMatch(spanishPart) && (k < unit.englishParts.length -1 )) {
                 englishLineSpans.add(const TextSpan(text: " "));
            } else if (!RegExp(r"\s$").hasMatch(part)  && (k < unit.englishParts.length -1 )) { // if punctuation doesn't have trailing space
                 englishLineSpans.add(const TextSpan(text: " "));
            }
        }


        return Padding(
          key: ValueKey(unit.id), // For stable list updates
          padding: const EdgeInsets.symmetric(vertical: 10.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SelectableText(
                unit.spanishSentenceText,
                style: TextStyle(
                  fontSize: Theme.of(context).textTheme.bodyLarge?.fontSize ?? 17.0,
                  color: Theme.of(context).colorScheme.onSurface,
                  fontWeight: FontWeight.w500,
                  height: 1.4,
                ),
              ),
              const SizedBox(height: 5.0),
              SelectableText.rich(
                TextSpan(children: englishLineSpans),
                 style: const TextStyle(height: 1.4),
              ),
            ],
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Tooltip(
            message: widget.article.title ?? 'Article Detail',
            child: Text(widget.article.title ?? 'Article Detail', overflow: TextOverflow.ellipsis)
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.translate),
            onPressed: _showInteractiveTranslator,
            tooltip: 'Open Full Translator',
          ),
          IconButton(
            icon: const Icon(Icons.open_in_browser),
            onPressed: () => _launchOriginalArticleUrl(widget.article.link),
            tooltip: 'Open Original Article',
          ),
        ],
      ),
      body: Scrollbar(
        controller: _scrollController,
        thumbVisibility: true,
        child: SingleChildScrollView( 
          controller: _scrollController,
          padding: const EdgeInsets.fromLTRB(16.0, 16.0, 16.0, 32.0), // More bottom padding
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (widget.article.title != null && widget.article.title!.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(bottom: 4.0),
                  child: Text(widget.article.title!, 
                        style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold)
                  ),
                ),
              if (widget.article.pubDate != null) 
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4.0), 
                  child: Text(
                    "Published: ${widget.article.pubDate.toString()}", // Consider formatting date
                    style: Theme.of(context).textTheme.bodySmall
                  )
                ),
              if (widget.article.dc?.creator != null) 
                Padding(
                  padding: const EdgeInsets.only(bottom: 12.0), 
                  child: Text(
                    'By: ${widget.article.dc!.creator}',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(fontStyle: FontStyle.italic)
                  )
                ),
              
              _buildTranslatedArticleView(context),

            ],
          ),
        ),
      ),
    );
  }
}
