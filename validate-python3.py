#! /usr/bin/python
# DZ 2018-11-04: Trying to port the validator to Python 3.
import fileinput
import sys
import io
import os.path
import logging
# According to https://stackoverflow.com/questions/1832893/python-regex-matching-unicode-properties,
# the regex module has the same API as re but it can check Unicode character properties using \p{}
# as in Perl.
#import re
import regex as re
import file_util
import traceback
import argparse


THISDIR=os.path.dirname(os.path.abspath(__file__)) # The folder where this script resides.

# Constants for the column indices
COLCOUNT=10
ID,FORM,LEMMA,UPOS,XPOS,FEATS,HEAD,DEPREL,DEPS,MISC=range(COLCOUNT)
COLNAMES='ID,FORM,LEMMA,UPOS,XPOS,FEATS,HEAD,DEPREL,DEPS,MISC'.split(',')
TOKENSWSPACE=MISC+1 #one extra constant

# Two global variables:
curr_line=0 # Current line in the input file
sentence_line=0 # The line in the input file on which the current sentence starts

error_counter={} # key: error type value: error count
warn_on_missing_files=set() # langspec files which you should warn about in case they are missing (can be deprel, edeprel, feat_val, tokens_w_space)
def warn(msg,error_type,lineno=True):
    """
    Print the warning. If lineno is True, print the exact line, otherwise
    print the line on which the current tree starts.
    """
    global curr_fname, curr_line, sentence_line, error_counter, tree_counter, args
    error_counter[error_type]=error_counter.get(error_type,0)+1
    if not args.quiet:
        if args.max_err>0 and error_counter[error_type]==args.max_err:
            print((u"...suppressing further errors regarding "+error_type).encode(args.err_enc), sys.stderr)
        elif args.max_err>0 and error_counter[error_type]>args.max_err:
            pass #suppressed
        else:
            if len(args.input)>1: #several files, should report which one
                if curr_fname=="-":
                    fn="(in STDIN) "
                else:
                    fn="(in "+os.path.basename(curr_fname)+") "
            else:
                fn=""
            if lineno:
                print(("[%sLine                   %d]: %s"%(fn,curr_line,msg)).encode(args.err_enc), file=sys.stderr)
            else:
                print(("[%sTree number %d on line %d]: %s"%(fn,tree_counter,sentence_line,msg)).encode(args.err_enc), file=sys.stderr)

###### Support functions

def is_whitespace(line):
    return re.match(r"^\s+$", line)

def is_word(cols):
    return re.match(r"^[1-9][0-9]*$", cols[ID])

def is_multiword_token(cols):
    return re.match(r"^[0-9]+-[0-9]+$", cols[ID])

def is_empty_node(cols):
    return re.match(r"^[0-9]+\.[0-9]+$", cols[ID])

def parse_empty_node_id(cols):
    m = re.match(r"^([0-9]+)\.([0-9]+)$", cols[ID])
    assert m, 'parse_empty_node_id with non-empty node'
    return m.groups()



#==============================================================================
# Level 1 tests. Only CoNLL-U backbone. Values can be empty or non-UD.
#==============================================================================

def trees(inp, tag_sets, args):
    """
    `inp` a file-like object yielding lines as unicode
    `tag_sets` and `args` are needed for choosing the tests

    This function does elementary checking of the input and yields one
    sentence at a time from the input stream.
    """
    global curr_line, sentence_line
    comments=[] # List of comment lines to go with the current sentence
    lines=[] # List of token/word lines of the current sentence
    for line_counter, line in enumerate(inp):
        curr_line=line_counter+1
        line=line.rstrip(u"\n")
        if is_whitespace(line):
            warn('Spurious line that appears empty but is not; there are whitespace characters.', 'Format')
            # We will pretend that the line terminates a sentence in order to avoid subsequent misleading error messages.
            if lines:
                yield comments, lines
                comments=[]
                lines=[]
        elif not line: # empty line
            if lines: # sentence done
                yield comments, lines
                comments=[]
                lines=[]
            else:
                warn('Spurious empty line. Only one empty line is expected after every sentence.', 'Format')
        elif line[0]=='#':
            if not lines: # before sentence
                comments.append(line)
            else:
                warn('Spurious comment line. Comments are only allowed before a sentence.', 'Format')
        elif line[0].isdigit():
            if not lines: # new sentence
                sentence_line=curr_line
            cols=line.split(u"\t")
            if len(cols)!=COLCOUNT:
                warn('The line has %d columns but %d are expected.'%(len(cols), COLCOUNT), 'Format')
            lines.append(cols)
            validate_cols_level1(cols)
            if args.level > 1:
                validate_cols(cols,tag_sets,args)
        else: # A line which is neither a comment nor a token/word, nor empty. That's bad!
            warn("Spurious line: '%s'. All non-empty lines should start with a digit or the # character."%(line), 'Format')
    else: # end of file
        if comments or lines: # These should have been yielded on an empty line!
            warn('Missing empty line after the last tree.', 'Format')
            yield comments, lines

###### Tests applicable to a single row indpendently of the others

whitespace_re=re.compile('.*\s',re.U)
whitespace2_re=re.compile('.*\s\s', re.U)
def validate_cols_level1(cols):
    """
    Tests that can run on a single line and pertain only to the CoNLL-U file
    format, not to predefined sets of UD tags.
    """
    # Some whitespace may be permitted in FORM, LEMMA and MISC but not elsewhere.
    for col_idx in range(MISC+1):
        if col_idx >= len(cols):
            break # this has been already reported in trees()
        # Must never be empty
        if not cols[col_idx]:
            warn('Empty value in column %s'%(COLNAMES[col_idx]), 'Format')
        else:
            # Must never have leading/trailing whitespace
            if cols[col_idx][0].isspace():
                warn('Initial whitespace not allowed in column %s'%(COLNAMES[col_idx]), 'Format')
            if cols[col_idx][-1].isspace():
                warn('Trailing whitespace not allowed in column %s'%(COLNAMES[col_idx]), 'Format')
            # Must never contain two consecutive whitespace characters
            if whitespace2_re.match(cols[col_idx]):
                warn('Two or more consecutive whitespace characters not allowed in column %s'%(COLNAMES[col_idx]), 'Format')
    # These columns must not have whitespace
    for col_idx in (ID,UPOS,XPOS,FEATS,HEAD,DEPREL,DEPS):
        if col_idx >= len(cols):
            break # this has been already reported in trees()
        if whitespace_re.match(cols[col_idx]):
            warn("White space not allowed in the %s column: '%s'"%(COLNAMES[col_idx], cols[col_idx]), 'Format')
    # Check for the format of the ID value. (ID must not be empty.)
    if not (is_word(cols) or is_empty_node(cols) or is_multiword_token(cols)):
        warn("Unexpected ID format '%s'" % cols[ID], 'Format')

##### Tests applicable to the whole tree

interval_re=re.compile('^([0-9]+)-([0-9]+)$',re.U)
def validate_ID_sequence(tree):
    """
    Validates that the ID sequence is correctly formed.
    """
    words=[]
    tokens=[]
    current_word_id, next_empty_id = 0, 1
    for cols in tree:
        if not is_empty_node(cols):
            next_empty_id = 1    # reset sequence
        if is_word(cols):
            t_id=int(cols[ID])
            current_word_id = t_id
            words.append(t_id)
            # Not covered by the previous interval?
            if not (tokens and tokens[-1][0]<=t_id and tokens[-1][1]>=t_id):
                tokens.append((t_id,t_id)) # nope - let's make a default interval for it
        elif is_multiword_token(cols):
            match=interval_re.match(cols[ID]) # Check the interval against the regex
            if not match:
                warn("Spurious token interval definition: '%s'."%cols[ID], 'Format', lineno=False)
                continue
            beg,end=int(match.group(1)),int(match.group(2))
            if not ((not words and beg == 1) or (words and beg == words[-1]+1)):
                warn('Multiword range not before its first word', 'Format')
                continue
            tokens.append((beg,end))
        elif is_empty_node(cols):
            word_id, empty_id = (int(i) for i in parse_empty_node_id(cols))
            if word_id != current_word_id or empty_id != next_empty_id:
                warn('Empty node id %s, expected %d.%d' %
                     (cols[ID], current_word_id, next_empty_id), 'Format')
            next_empty_id += 1
    # Now let's do some basic sanity checks on the sequences
    wrdstrseq = ','.join(str(x) for x in words)
    expstrseq = ','.join(str(x) for x in range(1, len(words)+1)) # Words should form a sequence 1,2,...
    if wrdstrseq != expstrseq:
        warn("Words do not form a sequence. Got '%s'. Expected '%s'."%(wrdstrseq, expstrseq), 'Format', lineno=False)
    # Check elementary sanity of word intervals
    for (b,e) in tokens:
        if e<b: # end before beginning
            warn('Spurious token interval %d-%d'%(b,e), 'Format')
            continue
        if b<1 or e>len(words): # out of range
            warn('Spurious token interval %d-%d (out of range)'%(b,e), 'Format')
            continue

def validate_token_ranges(tree):
    """
    Checks that the word ranges for multiword tokens are valid.
    """
    covered = set()
    for cols in tree:
        if not is_multiword_token(cols):
            continue
        m = interval_re.match(cols[ID])
        if not m:
            warn('Failed to parse ID %s' % cols[ID], 'Format')
            continue
        start, end = m.groups()
        try:
            start, end = int(start), int(end)
        except ValueError:
            assert False, 'internal error' # RE should assure that this works
        if not start < end:
            warn('Invalid range: %s' % cols[ID], 'Format')
            continue
        if covered & set(range(start, end+1)):
            warn('Range overlaps with others: %s' % cols[ID], 'Format')
        covered |= set(range(start, end+1))

def validate_newlines(inp):
    if inp.newlines and inp.newlines!='\n':
        warn('Only the unix-style LF line terminator is allowed', 'Format')



#==============================================================================
# Level 2 tests. Tree structure, universal tags, features and deprels.
#==============================================================================

###### Metadata tests #########

sentid_re=re.compile('^# sent_id\s*=\s*(\S+)$')
def validate_sent_id(comments,known_ids,lcode):
    matched=[]
    for c in comments:
        match=sentid_re.match(c)
        if match:
            matched.append(match)
        else:
            if c.startswith('# sent_id') or c.startswith('#sent_id'):
                warn("Spurious sent_id line: '%s' Should look like '# sent_id = xxxxx' where xxxxx is not whitespace. Forward slash reserved for special purposes." %c, 'Metadata')
    if not matched:
        warn('Missing the sent_id attribute.', 'Metadata')
    elif len(matched)>1:
        warn('Multiple sent_id attributes.', 'Metadata')
    else:
        # Uniqueness of sentence ids should be tested treebank-wide, not just file-wide.
        # For that to happen, all three files should be tested at once.
        sid=matched[0].group(1)
        if sid in known_ids:
            warn('Non-unique sent_id the sent_id attribute: '+sid, 'Metadata')
        if sid.count(u"/")>1 or (sid.count(u"/")==1 and lcode!=u"ud" and lcode!=u"shopen"):
            warn('The forward slash is reserved for special use in parallel treebanks: '+sid, 'Metadata')
        known_ids.add(sid)

def shorten(string):
    return string if len(string) < 25 else string[:20]+'[...]'

text_re=re.compile('^# text\s*=\s*(.+)$')
def validate_text_meta(comments,tree):
    matched=[]
    for c in comments:
        match=text_re.match(c)
        if match:
            matched.append(match)
    if not matched:
        warn('Missing the text attribute.', 'Metadata')
    elif len(matched)>1:
        warn('Multiple text attributes.', 'Metadata')
    else:
        stext=matched[0].group(1)
        if stext[-1].isspace():
            warn('The text attribute must not end with whitespace', 'Metadata')
        # Validate the text against the SpaceAfter attribute in MISC.
        skip_words=set()
        mismatch_reported=0 # do not report multiple mismatches in the same sentence; they usually have the same cause
        for cols in tree:
            if u"NoSpaceAfter=Yes" in cols[MISC]: # I leave this without the split("|") to catch all
                warn('NoSpaceAfter=Yes should be replaced with SpaceAfter=No', 'Metadata')
            if '.' in cols[ID]: # empty word
                if u"SpaceAfter=No" in cols[MISC]: # I leave this without the split("|") to catch all
                    warn('There should not be a SpaceAfter=No entry for empty words', 'Metadata')
                continue
            elif '-' in cols[ID]: # multi-word token
                beg,end=cols[ID].split('-')
                try:
                    begi,endi = int(beg),int(end)
                except ValueError as e:
                    warn('Non-integer range %s-%s (%s)'%(beg,end,e), 'Format')
                    begi,endi=1,0
                # If we see a MWtoken, add its words to an ignore-set - these will be skipped, and also checked for absence of SpaceAfter=No
                for i in range(begi, endi+1):
                    skip_words.add(str(i))
            elif cols[ID] in skip_words:
                if u"SpaceAfter=No" in cols[MISC]:
                    warn('There should not be a SpaceAfter=No entry for words which are a part of a token', 'Metadata')
                continue
            else:
                # Err, I guess we have nothing to do here. :)
                pass
            # So now we have either a MWtoken or a word which is also a token in its entirety
            if not stext.startswith(cols[FORM]):
                if not mismatch_reported:
                    warn("Mismatch between the text attribute and the FORM field. Form[%s] is '%s' but text is '%s...'" %(cols[ID], cols[FORM], stext[:len(cols[FORM])+20]), 'Metadata', False)
                    mismatch_reported=1
            else:
                stext=stext[len(cols[FORM]):] # eat the form
                if u"SpaceAfter=No" not in cols[MISC].split("|"):
                    if args.check_space_after and (stext) and not stext[0].isspace():
                        warn("SpaceAfter=No is missing in the MISC field of node #%s because the text is '%s'" %(cols[ID], shorten(cols[FORM]+stext)), 'Metadata')
                    stext=stext.lstrip()
        if stext:
            warn("Extra characters at the end of the text attribute, not accounted for in the FORM fields: '%s'"%stext, 'Metadata')

###### Tests applicable to a single row indpendently of the others

def validate_cols(cols, tag_sets, args):
    """
    All tests that can run on a single line. Done as soon as the line is read,
    called from trees() if level>1.
    """
    validate_whitespace(cols,tag_sets) # level 2
    if is_word(cols) or is_empty_node(cols):
        validate_character_constraints(cols) # level 2
        validate_features(cols, tag_sets, args) # level 2 and up (relevant code checks whether higher level is required)
        validate_pos(cols,tag_sets) # level 2
    elif is_multiword_token(cols):
        validate_token_empty_vals(cols)
    # else do nothing; we have already reported wrong ID format at level 1
    if is_word(cols):
        validate_deprels(cols, tag_sets, args) # level 2 and up
    elif is_empty_node(cols):
        validate_empty_node_empty_vals(cols) # level 2
        # TODO check also the following:
        # - DEPS are connected and non-acyclic
        # (more, what?)

def validate_whitespace(cols,tag_sets):
    """
    Checks a single line for disallowed whitespace.
    Here we assume that all language-independent whitespace-related tests have
    already been done in validate_cols_level1(), so we only check for words
    with spaces that are explicitly allowed in a given language.
    """
    for col_idx in (FORM,LEMMA):
        if col_idx >= len(cols):
            break # this has been already reported in trees()
        if whitespace_re.match(cols[col_idx]) is not None:
            # Whitespace found - does it pass?
            for regex in tag_sets[TOKENSWSPACE]:
                match=regex.match(cols[col_idx])
                if match and match.group(0)==cols[col_idx]:
                    break # We have a full match from beginning to end
            else:
                warn_on_missing_files.add('tokens_w_space')
                warn("'%s' in column %s is not on the list of exceptions allowed to contain whitespace (data/tokens_w_space.LANG files)."%(cols[col_idx], COLNAMES[col_idx]), 'Format')

def validate_token_empty_vals(cols):
    """
    Checks that a multi-word token has _ empty values in all fields except MISC.
    This is required by UD guidelines although it is not a problem in general,
    therefore a level 2 test.
    """
    assert is_multiword_token(cols), 'internal error'
    for col_idx in range(LEMMA,MISC): #all columns in the LEMMA-DEPS range
        if cols[col_idx]!=u"_":
            warn("A multi-word token line must have '_' in the column %s. Now: '%s'."%(COLNAMES[col_idx], cols[col_idx]), 'Format')

def validate_empty_node_empty_vals(cols):
    """
    Checks that an empty node has _ empty values in HEAD and DEPREL. This is
    required by UD guidelines but not necessarily by CoNLL-U, therefore
    a level 2 test.
    """
    assert is_empty_node(cols), 'internal error'
    for col_idx in (HEAD, DEPREL):
        if cols[col_idx]!=u"_":
            warn("An empty node must have '_' in the column %s. Now: '%s'."%(COLNAMES[col_idx], cols[col_idx]), 'Format')

# Ll ... lowercase Unicode letters
# Lm ... modifier Unicode letters (e.g., superscript h)
# Lo ... other Unicode letters (all caseless scripts, e.g., Arabic)
# M .... combining diacritical marks
# Underscore is allowed between letters but not at beginning, end, or next to another underscore.
edeprelpart_resrc = '[\p{Ll}\p{Lm}\p{Lo}\p{M}]+(_[\p{Ll}\p{Lm}\p{Lo}\p{M}]+)*';
# There must be always the universal part, consisting only of ASCII letters.
# There can be up to three additional, colon-separated parts: subtype, preposition and case.
# One of them, the preposition, may contain Unicode letters. We do not know which one it is
# (only if there are all four parts, we know it is the third one).
# ^[a-z]+(:[a-z]+)?(:[\p{Ll}\p{Lm}\p{Lo}\p{M}]+(_[\p{Ll}\p{Lm}\p{Lo}\p{M}]+)*)?(:[a-z]+)?$
edeprel_resrc = '^[a-z]+(:[a-z]+)?(:' + edeprelpart_resrc + ')?(:[a-z]+)?$'
edeprel_re = re.compile(edeprel_resrc, re.U)
def validate_character_constraints(cols):
    """
    Checks general constraints on valid characters, e.g. that UPOS
    only contains [A-Z].
    """
    if is_multiword_token(cols):
        return
    if UPOS >= len(cols):
        return # this has been already reported in trees()
    if not (re.match(r"^[A-Z]+$", cols[UPOS]) or
            (is_empty_node(cols) and cols[UPOS] == u"_")):
        warn('Invalid UPOS value %s' % cols[UPOS], 'Morpho')
    if not (re.match(r"^[a-z]+(:[a-z]+)?$", cols[DEPREL]) or
            (is_empty_node(cols) and cols[DEPREL] == u"_")):
        warn('Invalid DEPREL value %s' % cols[DEPREL], 'Syntax')
    try:
        deps = deps_list(cols)
    except ValueError:
        warn('Failed for parse DEPS: %s' % cols[DEPS], 'Syntax')
        return
    if any(deprel for head, deprel in deps_list(cols)
           if not edeprel_re.match(deprel)):
        warn('Invalid value in DEPS: %s' % cols[DEPS], 'Syntax')

attr_val_re=re.compile('^([A-Z0-9][A-Z0-9a-z]*(?:\[[a-z0-9]+\])?)=(([A-Z0-9][A-Z0-9a-z]*)(,([A-Z0-9][A-Z0-9a-z]*))*)$',re.U)
val_re=re.compile('^[A-Z0-9][A-Z0-9a-z]*',re.U)
def validate_features(cols, tag_sets, args):
    """
    Checks general constraints on feature-value format. On level 3 and higher,
    also checks that a feature-value pair is listed as approved.
    """
    if FEATS >= len(cols):
        return # this has been already reported in trees()
    feats=cols[FEATS]
    if feats==u"_":
        return True
    feat_list=feats.split(u"|")
    if [f.lower() for f in feat_list]!=sorted(f.lower() for f in feat_list):
        warn("Morphological features must be sorted: '%s'"%feats, 'Morpho')
    attr_set=set() # I'll gather the set of attributes here to check later than none is repeated
    for f in feat_list:
        match=attr_val_re.match(f)
        if match is None:
            warn("Spurious morphological feature: '%s'. Should be of the form attribute=value and must start with [A-Z0-9] and only contain [A-Za-z0-9]."%f, 'Morpho')
            attr_set.add(f) # to prevent misleading error "Repeated features are disallowed"
        else:
            # Check that the values are sorted as well
            attr=match.group(1)
            attr_set.add(attr)
            values=match.group(2).split(u",")
            if len(values)!=len(set(values)):
                warn("Repeated feature values are disallowed: %s"%feats, 'Morpho')
            if [v.lower() for v in values]!=sorted(v.lower() for v in values):
                warn("If an attribute has multiple values, these must be sorted as well: '%s'"%f, 'Morpho')
            for v in values:
                if not val_re.match(v):
                    warn("Incorrect value '%s' in '%s'. Must start with [A-Z0-9] and only contain [A-Za-z0-9]."%(v,f), 'Morpho')
                # Level 2 tests character properties and canonical order but not that the f-v pair is known.
                # Level 3 also checks whether the feature value is on the list.
                if args.level > 2 and tag_sets[FEATS] is not None and attr+u"="+v not in tag_sets[FEATS]:
                    warn_on_missing_files.add("feat_val")
                    warn('Unknown attribute-value pair %s=%s'%(attr,v), 'Morpho')
    if len(attr_set)!=len(feat_list):
        warn('Repeated features are disallowed: %s'%feats, 'Morpho')

def validate_upos(cols,tag_sets):
    if UPOS >= len(cols):
        return # this has been already reported in trees()
    if tag_sets[UPOS] is not None and cols[UPOS] not in tag_sets[UPOS]:
        warn('Unknown UPOS tag: %s'%cols[UPOS], 'Morpho')

def validate_xpos(cols,tag_sets):
    if XPOS >= len(cols):
        return # this has been already reported in trees()
    # We currently do not have any list of known XPOS tags, hence tag_sets[XPOS] is None.
    if tag_sets[XPOS] is not None and cols[XPOS] not in tag_sets[XPOS]:
        warn('Unknown XPOS tag: %s'%cols[XPOS], 'Morpho')

def validate_pos(cols,tag_sets):
    if not (is_empty_node(cols) and cols[UPOS] == '_'):
        validate_upos(cols, tag_sets)
    if not (is_empty_node(cols) and cols[XPOS] == '_'):
        validate_xpos(cols, tag_sets)

def lspec2ud(deprel):
    return deprel.split(':', 1)[0]

def validate_deprels(cols, tag_sets, args):
    if DEPREL >= len(cols):
        return # this has been already reported in trees()
    # Test only the universal part if testing at universal level.
    deprel = cols[DEPREL]
    if args.level < 4:
        deprel = lspec2ud(deprel)
    if tag_sets[DEPREL] is not None and deprel not in tag_sets[DEPREL]:
        warn_on_missing_files.add("deprel")
        warn('Unknown UD DEPREL: %s'%cols[DEPREL], 'Syntax')
    if tag_sets[DEPS] is not None and cols[DEPS]!='_':
        for head_deprel in cols[DEPS].split(u"|"):
            try:
                head,deprel=head_deprel.split(u":",1)
            except ValueError:
                warn("Malformed head:deprel pair '%s'"%head_deprel, 'Syntax')
                continue
            if args.level < 4:
                deprel = lspec2ud(deprel)
            if deprel not in tag_sets[DEPS]:
                warn_on_missing_files.add("edeprel")
                warn("Unknown enhanced dependency relation '%s' in '%s'"%(deprel,head_deprel), 'Syntax')

##### Tests applicable to the whole tree

def subset_to_words(tree):
    """
    Only picks the word lines, skips multiword token and empty node lines.
    """
    return [cols for cols in tree if is_word(cols)]

def subset_to_words_and_empty_nodes(tree):
    """
    Only picks word and empty node lines, skips multiword token lines.
    """
    return [cols for cols in tree if is_word(cols) or is_empty_node(cols)]

def deps_list(cols):
    if DEPS >= len(cols):
        return # this has been already reported in trees()
    if cols[DEPS] == u'_':
        deps = []
    else:
        deps = [hd.split(u':',1) for hd in cols[DEPS].split(u'|')]
    if any(hd for hd in deps if len(hd) != 2):
        raise ValueError(u'malformed DEPS: %s' % cols[DEPS])
    return deps

def validate_ID_references(tree):
    """
    Validates that HEAD and DEPRELS reference existing IDs.
    """
    word_tree = subset_to_words_and_empty_nodes(tree)
    ids = set([cols[ID] for cols in word_tree])
    def valid_id(i):
        return i in ids or i == u'0'
    def valid_empty_head(cols):
        return cols[HEAD] == '_' and is_empty_node(cols)
    for cols in word_tree:
        if HEAD >= len(cols):
            return # this has been already reported in trees()
        if not (valid_id(cols[HEAD]) or valid_empty_head(cols)):
            warn('Undefined ID in HEAD: %s' % cols[HEAD], 'Format')
        try:
            deps = deps_list(cols)
        except ValueError:
            warn("Failed to parse DEPS: '%s'" % cols[DEPS], 'Format')
            continue
        for head, deprel in deps:
            if not valid_id(head):
                warn("Undefined ID in DEPS: '%s'" % head, 'Format')

def proj(node,s,deps,depth,max_depth):
    """
    Recursive calculation of the projection of a node `node` (1-based
    integer). The nodes, as they get discovered` are added to the set
    `s`. Deps is a dictionary node -> set of children.
    """
    if max_depth is not None and depth==max_depth:
        return
    for dependent in deps.get(node,[]):
        if dependent in s:
            warn('Loop from %s' % dependent, 'Syntax')
            continue
        s.add(dependent)
        proj(dependent,s,deps,depth+1,max_depth)

def validate_root(tree):
    """
    Validates that DEPREL is "root" iff HEAD is 0.
    """
    for cols in subset_to_words_and_empty_nodes(tree):
        if HEAD >= len(cols):
            continue # this has been already reported in trees()
        if cols[HEAD] == '0':
            if cols[DEPREL] != 'root':
                warn("DEPREL must be 'root' if HEAD is 0", 'Syntax')
        else:
            if cols[DEPREL] == 'root':
                warn("DEPREL cannot be 'root' if HEAD is not 0", 'Syntax')

def validate_deps(tree):
    """
    Validates that DEPS is correctly formatted and that there are no
    self-loops in DEPS.
    """
    for cols in subset_to_words_and_empty_nodes(tree):
        if DEPS >= len(cols):
            continue # this has been already reported in trees()
        try:
            deps = deps_list(cols)
            heads = [float(h) for h, d in deps]
        except ValueError:
            warn("Failed to parse DEPS: '%s'" % cols[DEPS], 'Format')
            return
        if heads != sorted(heads):
            warn("DEPS not sorted by head index: '%s'" % cols[DEPS], 'Format')
        try:
            id_ = float(cols[ID])
        except ValueError:
            warn("Non-numeric ID: '%s'" % cols[ID], 'Format')
            return
        if id_ in heads:
            warn("Self-loop in DEPS for '%s'" % cols[ID], 'Format')

def validate_tree(tree):
    """
    Validates that all words can be reached from the root and that
    there are no self-loops in HEAD.
    """
    deps={} #node -> set of children
    word_tree=subset_to_words(tree)
    for cols in word_tree:
        if HEAD >= len(cols):
            continue # this has been already reported in trees()
        if cols[HEAD]=='_':
            warn('Empty head for word ID %s' % cols[ID], 'Format', lineno=False)
            continue
        try:
            id_ = int(cols[ID])
        except ValueError:
            warn('Non-integer ID: %s' % cols[ID], 'Format', lineno=False)
            continue
        try:
            head = int(cols[HEAD])
        except ValueError:
            warn('Non-integer head for word ID %s' % cols[ID], 'Format', lineno=False)
            continue
        if head == id_:
            warn('HEAD == ID for %s' % cols[ID], 'Format', lineno=False)
            continue
        deps.setdefault(head, set()).add(id_)
    root_deps=set()
    proj(0,root_deps,deps,0,1)
    if len(root_deps)>1 and args.single_root:
        warn('Multiple root words: %s'%list(root_deps), 'Syntax', lineno=False)
    root_proj=set()
    proj(0,root_proj,deps,0,None)
    unreachable=set(range(1,len(word_tree)+1))-root_proj # all words minus those reachable from root
    if unreachable:
        warn('Non-tree structure. Words %s are not reachable from the root 0.'%(','.join(str(w) for w in sorted(unreachable))), 'Syntax', lineno=False)



#==============================================================================
# Level 3 tests. Annotation content vs. the guidelines (only universal tests).
#==============================================================================

def validate_left_to_right_relations(cols):
    """
    Certain UD relations must always go left-to-right.
    Here we currently check the rule for the basic dependencies.
    The same should also be tested for the enhanced dependencies!
    """
    if is_multiword_token(cols):
        return
    if DEPREL >= len(cols):
        return # this has been already reported in trees()
    #if cols[DEPREL] == u"conj":
    if re.match(r"^(conj|fixed|flat)", cols[DEPREL]):
        ichild = int(cols[ID])
        iparent = int(cols[HEAD])
        if ichild < iparent:
            warn("Violation of guidelines: relation '%s' must go left-to-right" % cols[DEPREL], 'Syntax')

def validate_annotation(tree):
    """
    Checks universally valid consequences of the annotation guidelines.
    """
    deps={} # node -> set of children
    word_tree=subset_to_words(tree)
    for cols in word_tree:
        if HEAD >= len(cols):
            continue # this has been already reported in trees()
        if cols[HEAD]=='_':
            continue # this has been already reported in validate_tree()
        try:
            id_ = int(cols[ID])
        except ValueError:
            continue # this has been already reported in validate_tree()
        try:
            head = int(cols[HEAD])
        except ValueError:
            continue # this has been already reported in validate_tree()
        # Incrementally build the set of children of every node.
        deps.setdefault(head, set()).add(id_)
        # Content tests that only need to see one word.
        if is_word(cols) or is_empty_node(cols):
            validate_left_to_right_relations(cols)



#==============================================================================
# Main part.
#==============================================================================

def validate(inp,out,args,tag_sets,known_sent_ids):
    global tree_counter
    for comments,tree in trees(inp,tag_sets,args):
        tree_counter+=1
        #the individual lines have been validated already in trees()
        #here go tests which are done on the whole tree
        validate_ID_sequence(tree) # level 1
        validate_token_ranges(tree) # level 1
        if args.level > 1:
            validate_ID_references(tree) # level 2
            validate_root(tree) # level 2
            validate_deps(tree) # level 2 and up
            validate_tree(tree) # level 2
            validate_sent_id(comments, known_sent_ids, args.lang) # level 2
            if args.check_tree_text:
                validate_text_meta(comments,tree) # level 2
            if args.level > 2:
                validate_annotation(tree) # level 3
        if args.echo_input:
            file_util.print_tree(comments,tree,out)
    validate_newlines(inp) # level 1

def load_file(f_name):
    res=set()
    with io.open(f_name, 'r', encoding='utf-8') as f:
        for line in f:
            line=line.strip()
            if not line or line.startswith('#'):
                continue
            res.add(line)
    return res

def load_set(f_name_ud,f_name_langspec,validate_langspec=False,validate_enhanced=False):
    """
    Loads a list of values from the two files, and returns their
    set. If f_name_langspec doesn't exist, loads nothing and returns
    None (ie this taglist is not checked for the given language). If f_name_langspec
    is None, only loads the UD one. This is probably only useful for CPOS which doesn't
    allow language-specific extensions. Set validate_langspec=True when loading basic dependencies.
    That way the language specific deps will be checked to be truly extensions of UD ones.
    Set validate_enhanced=True when loading enhanced dependencies. They will be checked to be
    truly extensions of universal relations, too; but a more relaxed regular expression will
    be checked because enhanced relations may contain stuff that is forbidden in the basic ones.
    """
    res=load_file(os.path.join(THISDIR,"data",f_name_ud))
    #Now res holds UD
    #Next load and optionally check the langspec extensions
    if f_name_langspec is not None and f_name_langspec!=f_name_ud:
        path_langspec = os.path.join(THISDIR,"data",f_name_langspec)
        if os.path.exists(path_langspec):
            global curr_fname
            curr_fname = path_langspec # so warn() does not fail on undefined curr_fname
            l_spec=load_file(path_langspec)
            for v in l_spec:
                if validate_enhanced:
                    # We are reading the list of language-specific dependency relations in the enhanced representation
                    # (i.e., the DEPS column, not DEPREL). Make sure that they match the regular expression that
                    # restricts enhanced dependencies.
                    if not edeprel_re.match(v):
                        warn("Spurious language-specific enhanced relation '%s' - it does not match the regular expression that restricts enhanced relations."%v, 'Syntax', lineno=False)
                        continue
                elif validate_langspec:
                    # We are reading the list of language-specific dependency relations in the basic representation
                    # (i.e., the DEPREL column, not DEPS). Make sure that they match the regular expression that
                    # restricts basic dependencies. (In particular, that they do not contain extensions allowed in
                    # enhanced dependencies, which should be listed in a separate file.)
                    if not re.match(r"^[a-z]+(:[a-z]+)?$", v):
                        warn("Spurious language-specific relation '%s' - in basic UD, it must match '^[a-z]+(:[a-z]+)?'."%v, 'Syntax', lineno=False)
                        continue
                if validate_langspec or validate_enhanced:
                    try:
                        parts=v.split(':')
                        if parts[0] not in res:
                            warn("Spurious language-specific relation '%s' - not an extension of any UD relation."%v, 'Syntax', lineno=False)
                            continue
                    except:
                        warn("Spurious language-specific relation '%s' - not an extension of any UD relation."%v, 'Syntax', lineno=False)
                        continue
                res.add(v)
    return res

if __name__=="__main__":
    opt_parser = argparse.ArgumentParser(description="CoNLL-U validation script")

    io_group=opt_parser.add_argument_group("Input / output options")
    io_group.add_argument('--noecho', dest="echo_input", action="store_false", default=False, help='Do not echo the input CoNLL-U data onto output. (for backward compatibility)')
    io_group.add_argument('--echo', dest="echo_input", action="store_true", default=False, help='Echo the input CoNLL-U data onto output. (for backward compatibility)')
    io_group.add_argument('--quiet', dest="quiet", action="store_true", default=False, help='Do not print any error messages. Exit with 0 on pass, non-zero on fail. Implies --noecho.')
    io_group.add_argument('--max-err', action="store", type=int, default=20, help='How many errors to output before exiting? 0 for all. Default: %(default)d.')
    io_group.add_argument('--err-enc', action="store", default="utf-8", help='Encoding of the error message output. Default: %(default)s. Note that the CoNLL-U output is by definition always utf-8.')
    io_group.add_argument('input', nargs='*', help='Input file name(s), or "-" or nothing for standard input.')
    #I don't think output makes much sense now that we allow multiple inputs, so it will default to /dev/stdout
    #io_group.add_argument('output', nargs='', help='Output file name, or "-" or nothing for standard output.')

    list_group=opt_parser.add_argument_group("Tag sets","Options relevant to checking tag sets.")
    list_group.add_argument("--lang", action="store", required=True, default=None, help="Which langauge are we checking? If you specify this (as a two-letter code), the tags will be checked using the language-specific files in the data/ directory of the validator. It's also possible to use 'ud' for checking compliance with purely ud.")

    tree_group=opt_parser.add_argument_group("Tree constraints","Options for checking the validity of the tree.")
    tree_group.add_argument("--level", action="store", type=int, default=5, dest="level", help="Level 1: CoNLL-U backbone. Level 2: UD format. Level 3: UD contents.")
    tree_group.add_argument("--multiple-roots", action="store_false", default=True, dest="single_root", help="Allow trees with several root words (single root required by default).")

    meta_group=opt_parser.add_argument_group("Metadata constraints","Options for checking the validity of tree metadata.")
    meta_group.add_argument("--no-tree-text", action="store_false", default=True, dest="check_tree_text", help="Do not test tree text. For internal use only, this test is required and on by default.")
    meta_group.add_argument("--no-space-after", action="store_false", default=True, dest="check_space_after", help="Do not test presence of SpaceAfter=No.")

    args = opt_parser.parse_args() #Parsed command-line arguments
    error_counter={} #Incremented by warn()  {key: error type value: its count}
    tree_counter=0

    # Level of validation
    if args.level < 1:
        print('Option --level must not be less than 1; changing from %d to 1' % args.level, file=sys.stderr)
        args.level = 1
    # No language-specific tests for levels 1-3
    if args.level < 4:
        args.lang = 'ud'

    if args.quiet:
        args.echo_input=False

    tagsets={XPOS:None,UPOS:None,FEATS:None,DEPREL:None,DEPS:None,TOKENSWSPACE:None} #sets of tags for every column that needs to be checked, plus (in v2) other sets, like the allowed tokens with space

    if args.lang:
        tagsets[DEPREL]=load_set("deprel.ud","deprel."+args.lang,validate_langspec=True)
        # All relations available in DEPREL are also allowed in DEPS.
        # In addition, there might be relations that are only allowed in DEPS.
        # One of them, "ref", is universal and we currently list it directly in the code here, instead of creating a file "edeprel.ud".
        tagsets[DEPS]=tagsets[DEPREL]|{"ref"}|load_set("deprel.ud","edeprel."+args.lang,validate_enhanced=True)
        tagsets[FEATS]=load_set("feat_val.ud","feat_val."+args.lang)
        tagsets[UPOS]=load_set("cpos.ud",None)
        tagsets[TOKENSWSPACE]=load_set("tokens_w_space.ud","tokens_w_space."+args.lang)
        tagsets[TOKENSWSPACE]=[re.compile(regex,re.U) for regex in tagsets[TOKENSWSPACE]] #...turn into compiled regular expressions

    out=sys.stdout # hard-coding - does this ever need to be anything else?

    try:
        known_sent_ids=set()
        open_files=[]
        if args.input==[]:
            args.input.append('-')
        for fname in args.input:
            if fname=='-':
                # Set PYTHONIOENCODING=utf-8 before starting Python. See https://docs.python.org/3/using/cmdline.html#envvar-PYTHONIOENCODING
                # Otherwise ANSI will be read in Windows and locale-dependent encoding will be used elsewhere.
                open_files.append(sys.stdin)
            else:
                open_files.append(io.open(fname, 'r', encoding='utf-8'))
        for curr_fname,inp in zip(args.input,open_files):
            validate(inp,out,args,tagsets,known_sent_ids)
    except:
        warn('Exception caught!', 'Format')
        # If the output is used in an HTML page, it must be properly escaped
        # because the traceback can contain e.g. "<module>". However, escaping
        # is beyond the goal of validation, which can be also run in a console.
        traceback.print_exc()

    if not error_counter:
        if not args.quiet:
            print('*** PASSED ***', file=sys.stderr)
        sys.exit(0)
    else:
        if not args.quiet:
            print('*** FAILED *** with %d errors'%sum(v for k,v in error_counter.iteritems()), file=sys.stderr)
            for k,v in sorted(error_counter.items()):
                print(k+'errors:'+v, file=sys.stderr)
        for f_name in sorted(warn_on_missing_files):
            filepath = os.path.join(THISDIR, 'data', f_name+'.'+args.lang)
            if not os.path.exists(filepath):
                print('The language-specific file %s does not exist.'%filepath, file=sys.stderr)
        sys.exit(1)