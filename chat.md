task : Al Teel: Convert Architectural Casework Elevations (PDF) into Editable AuteCAD DWG Files with Self-Training
Interface

Project Description

i need a custom Al tool that automatically reads architectural casework elevation drawings (PDFs) and generates
complete. editable AuteCAD DWG files using my existing multiple block libraries.

The tool must detect cabinets. sinks, fixtures, shelving. ceunterteps, and miscellaneous equipment. then place the
correct blocks with accurate dimensions. ceuntertep outlines, and section views.

It must also include a natural language self-training interface so a non-technical user can teach and refine the Al
using plain English rules or by correcting the output drawing.

This is Phase 1 (Proof of Concept) of a larger initiative. Future phases will expand to multiple elevations and
additional manufacturers.

Sample Flies Provided

Before: Architectural elevation A407 (page 26)

After: Mott shop drawing 2-08 (page 30)

Full block library, spec sheets, and catalogs will be supplied

Key Requirements

input

PDF casework elevation drawings (sometimes original DWG)

My organized AuteCAD block library

Project-specific catalogs and reference documents

Output

Clean, editable AutoCAD DWG file containing:

Correctly placed blocks for all detected casework, sinks, fixtures, shelving, etc.

Accurate dimensions (height, width, spacing)

Countertop outlines with detailed top-view information

Section views based on cabinet types

Proper layers, line types, and drafting standards

Visual flags / notes for any unmatched or uncertain items

Core Features

YOLO-based (or equivalent) object detection for cabinets, sinks. pegboards, etc.
Vision LLM assistance for annotation and context understanding

Block matching engine with fallback logic

Natural language rule engine ("teach' the Al in plain English)

Self-training interface (view, edit, enable/disable rules)

Drawing-based learning (compare Al DWG vs. user-corrected DWG)
Confidence warnings and visual flagging of uncertain items

Technical Preferences

Detection: YOLOv8 / YOLOv11 (fine-tuned on my samples) + Vision LLM (GPT-4o or Claude)
DWG generation: ezdxf (preferred for standalone) or pyautocad

Rule storage: Human-readable JSON/YAML

Training interface: Lightweight GUI (Tkinter / PyQt) or simple web interface
Deiiverables

Fully working Python tool (script + optional GUI)

Natural language rule trainer and visual rule manager

Clean DWG output meeting my drafting standards

Full source code. trained model weights, training scripts, and documentation
Setup guide and user manual

Log/ report of unmatched or low-confidence items

Timeline

POC Phase 1 (single elevation) within 2~3 weeks

Full Phase 1 within 6-8 weeks (flexible)

Budget

Please provide your fixed price for the POC 1 & P00 2 (single elevation with full DWG output + basic self-training
interface). Higher budget available for excellent quality and clean code.

How to Apply

Please reply with:

Your proposed technical approach (tools and libraries)

Estimated timeline for the POC 1

Fixed price for the P001

Links or screenshots of any similar past projects (CAD/DXF automation, technical drawing conversion, or vision Al
on drawings)

i will provide all sample files immediately upon hiring.

Looking forward to your proposals.

client :  Hi, have you done any cad projects before?

me : Hi, Matt

How are you?

Thanks for your asking.

Yes, l have worked on CAD-related automation projects before,
especially where drawings or structured visual layouts had to be
converted into editable output through custom logic and Python-
based processing.

in projects like yours, the important part is not only detecting objects
from the PDF, but also mapping them correctly into clean editable CAD
output with proper dimensions, layers, and drafting structure. l'm
comfortable with that kind of workflow using Python, computer vision,
and rule-based conversion logic.

For your case, I would approach it in 3 parts:

detect and classify casework items from the elevation PDF

match each item to the correct block/library component with fallback
rules

generate a clean editable DWG or DXF output, then add a simple
training interface so you can refine rules in plain English overtime

So yes, this is within the type of work i can handle.

If you want, I can also share a more technical breakdown of how i
would build the P00 1 for your exact workflow.

client : Sounds great, sure please share tech breakdown for poc 1

me : Sure, for P00 1, I would keep the scope focused on one elevation
workflow and make sure the output is already useful. editable. and
easy to improve later.

You send me:

the sample elevation PDF, the expected output example, your block
library, and any drafting rules or catalog references.

My POC 1 workflow would be:

First, l build the drawing parser layer.

This reads the PDF elevation, detects the main objects like cabinets,
sinks. shelving, fixtures, and ceuntertep areas, and extracts their
position, size, and relationships. For this, i would use a combination of
vision detection and rule-based geometry reading so the result is not
only visual but drafting-aware.

Second, i build the block matching engine.

Each detected object is matched against your block library using type,
size, and contextual rules. If there is no strong match, the system will
place a flagged placeholder and log it clearly instead of guessing
blindly.

Third, i generate the editable CAD output.

The output will be created as a clean DXF/DWG-ready drafting
structure with layers. block placement, dimensions. ceuntertep
outlines, and notes for uncertain items. i usually prefer ezdxf for
stable generation logic in the first phase.
Fourth, I add the basic self-training interface.

This will let you review detected items, see lowconfidence matches,
and teach new rules in plain English such as:

if a base cabinet is 36 inch wide and sits below sink symbol. use sink-
base block type A.

These rules will be stored in readable JSON or YAML so they can be
edited and expanded later.

Pec1 deliverable would be:

one working pipeline fora single elevation,

editable CAD output,

basic rule trainer.

match confidence log,

and source code with setup steps.

Estimated P00 1 timeline is about 1 to 2 weeks depending on sample
quality and block library consistency.

If helpful, I can also send you the exact module structure I would use
for the codebase so you can see how I would keep it clean and
scalable

client : Thank you — this is a very clear and well-structured plan. I like the
step-by—step approach and the focus on clean, editable output with
proper fallbacks.

Before we move forward. I just want to confirm a couple of quick
points:

1. For the detection layer, will you be using a fine-tuned "YOLO
model** (YOLOv8 or YOLOvl 1) or another specific object detection
approach?

2. Will you also use a "Vision LLM" (such as GPT-4o or Claude) to
help read annotations, dimensions. and context from the elevation?
3. For the paid test on one elevation (A407 _. 2-08 sample), my
budget is **$100 fixed". This would include:

- Detection + block mapping + product number placement

- Clean editable DXF/DWG output

- Basic rule trainer

- Confidence log / validation notes

If the test output is accurate and professional, I will immediately
award you the full single-elevation POC.

Does $120 for the test work for you? if yes, I can send the sample files
(Before PDF. After example, block library. and catalog references) right
away.

Looking forward to your reply.

me : Thank you. Yes. $120 for the paid test works for me.

To confirm your points:

1. For detection, i would use a fine~tuned YOLO model, most likely
YOL0v8 for the test phase because it is stable, fast to train, and a
good fit for this kind of object detection workfiow. if needed. i can later
upgrade or compare with YOL0v11 during the full POC.

2. Yes, I would also use a Vision LLM where it adds value, especially
for reading annotations, interpreting dimensions, and improving
context around ambiguous items. i would use it as a support layer,
while keeping the main pipeline rule-based and deterministic for
reliable CAD output.

For the paid test, i understand the scope is:

detection, block mapping, product number placement, clean editable
DXF/DWG output, basic rule trainer, and confidence log.

Please send the sample files, block library, and catalog references, and
i will review them carefully and start with the A407 to 2-08 test
workflow

client : Great. i will work on getting you all the info you need. Probebly i wont
have it till tomorrow

me : No problem 
Please send everything whenever you have it tomorrow, and i will
review it carefully as soon as it arrives so we can move smoothly into
the test phase

client : Do you need CAD blocks of the casework or do i need to make pdfs of
the casework blocks?

me : If you already have the casework blocks in CAD format like DWG or
DXF, that would be best for me.

That will make the block matching and clean editable output much
more accurate. since i can use the actual geometry, scale, and
insertion logic directly.

PDFs of the blocks can still be helpful as reference, but ideally I would
want the real CAD blocks first- if you have both, even better


client : the cad blocks were uploaded to the task. if there are any missing
blocks that you need just let me know. Lets do elevation E4 as the test
elevation

me : i will work with these first, and if I find that any specific block is
missing for accurate matching or output, 1 will let you know clearly.

E4 works well as the test elevation. Once i receive the rest of the files
and references. I will review everything and use E4 as the starting
sample for the paid test