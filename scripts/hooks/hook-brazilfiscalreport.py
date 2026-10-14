# Inclui a tabela de municípios e o brasão usados na DANFSe.
# Os módulos ficam como .py soltos na pasta do programa (e não compactados), para quem
# quiser trocar a biblioteca por outra versão, como a licença LGPL prevê.
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("brazilfiscalreport")
module_collection_mode = "py"
