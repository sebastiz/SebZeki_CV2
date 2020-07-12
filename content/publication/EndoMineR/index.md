+++
title = "EndoMineR for the extraction of endoscopic and associated pathology data from medical reports"
date = 2013-07-01T00:00:00
draft = false

# Authors. Comma separated list, e.g. `["Bob Smith", "David Jones"]`.
authors = ["Sebastian Zeki"]
            

# Publication type.
# Legend:
# 0 = Uncategorized
# 1 = Conference paper
# 2 = Journal article
# 3 = Manuscript
# 4 = Report
# 5 = Book
# 6 = Book section
publication_types = ["2"]

# Publication name and optional abbreviated version.
publication = "In *Journal of Open Source Software, 3(24), 701.*"
#publication_short = "In *ICMEW*"

# Abstract and optional shortened version.
abstract = "Medical data is increasingly kept in an electronic format worldwide (Bretthauer M. 2016).This serves many purposes including more efficient storage, distribution and accessibility of patient-focussed data. As important is the ability to analyse healthcare data for to optimize resource deployment and usage. The tools for the analysis are often statistical and rely on the provision of ‘clean’ datasets before this can be done. ‘Cleaning’ a dataset is often the most difficult aspect of any data analysis and involves the provision of meaningful and well-formatted data so that the interpretation of the analysis is not subject to the doubts of the data quality. The British Society of Gastroenterology recommends that all endoscopic data is kept in an electronic format particularly to facilitate audit and maintain standards through the Global Rating Scale (GRS) (Stebbing J. 2011). The endoscopic dataset is however only part of the patient’s story as many aspects of a patient’s gastroenterological care depend on the results of histopathological analysis of tissue taken during the examination. Pathology results are often available many days after the endoscopic result and usually stored in a separate data repository, although this may change with the arrival of an encompassing electronic patient record. Regardless of the method of storage, it is often difficult to associate the particular histopathological result with an endoscopic result. Further, even if the two data sets can be merged, a problem occurs in the isolation of various parts of each report such that each part can be individually analysed. Examples include the isolation of who the endoscopist was or the presence of dysplasia within a histopathology report. This is all the more difficult if the report is unstructured or partially structured free text. However if this can be done then many downstream analyses which benefit individual patients as well as the department, can be automated and include more complex analyses to determine follow-up regimes or endoscopic –pathologic lesion recognition performance. The EndoMineR package provides a comprehensive way to extract information from natural language endoscopy ann pathology reports as well as merging the two datasets so that pathology specimens are relevant to the endoscopy they came from. Furthermore the package also provides functions for the following types of analysis of endoscopic and pathological datasets: • 1. Patient surveillance. Examples including determining when patients should return for surveillance and who is overdue. • 2. Patient tracking. -Examples include determining the length of time since the last endoscopy, as well as aggregate functions such as finding how many endoscopies of a certain type have been done and predicting future burden." 
abstract_short = ""

# Is this a selected publication? (true/false)
selected = false

# Projects (optional).
#   Associate this publication with one or more of your projects.
#   Simply enter your project's folder or file name without extension.
#   E.g. `projects = ["deep-learning"]` references 
#   `content/project/deep-learning/index.md`.
#   Otherwise, set `projects = []`.
#projects = ["internal-project"]

# Tags (optional).
#   Set `tags = []` for no tags, or use the form `tags = ["A Tag", "Another Tag"]` for one or more tags.
tags = []

# Links (optional).
# url_pdf = "http://eprints.soton.ac.uk/352095/1/Cushen-IMV2013.pdf"
# url_preprint = "http://eprints.soton.ac.uk/352095/1/Cushen-IMV2013.pdf"
# url_code = "#"
# url_dataset = "#"
# url_project = ""
# url_slides = "#"
# url_video = "#"
# url_poster = "#"
#url_source = "https://onlinelibrary.wiley.com/doi/full/10.1111/cea.13279"

# Custom links (optional).
#   Uncomment line below to enable. For multiple links, use the form `[{...}, {...}, {...}]`.
#url_custom = [{name = "Custom Link", url = "http://example.org"}]

# Digital Object Identifier (DOI)
doi = "10.21105/joss.00701"

# Does this page contain LaTeX math? (true/false)
math = true

# Featured image
# To use, add an image named `featured.jpg/png` to your page's folder. 
[image]
  # Caption (optional)
  caption = "Image credit: [**Unsplash**](https://unsplash.com/photos/pLCdAaMFLTE)"

  # Focal point (optional)
  # Options: Smart, Center, TopLeft, Top, TopRight, Left, Right, BottomLeft, Bottom, BottomRight
  focal_point = ""
+++


